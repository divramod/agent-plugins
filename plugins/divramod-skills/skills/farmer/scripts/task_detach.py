#!/usr/bin/env python3
"""A farmer task whose Check runs longer than the inline limit runs detached (hal2 plan 0534, D3, D4).

The tick must stay short, so a task with `- **Limit**: <n> s` above DEFAULT_LIMIT (120 s) does not run its Check in
the tick: `start` launches a runner process in its own session, which runs the Check commands and writes the result
atomically to `<farmer state>/tasks/<task>.json`; the next tick reads it (`status`) and evaluates it like an inline
result, records "running" while the run is under its limit, and kills the run's process group past it (`terminate`).

  task_detach.py run <result file>     the runner (started by `start`, never by hand)

The result file (schema 1, one per task, overwritten by the next run, retention count 1):
  schema, task, state (starting | running | done), pid (the runner, its group's leader; 0 before it started),
  started, ended (UTC, ISO), limit (s), cmds (the Check commands), exit (0 ok, 1 failed, 124 timed out, null while
  it runs), output (the failure's tail), consumed (a tick evaluated a done result).
Writes go through a temp file renamed over the result (never in place); a path comes from the farmer's state folder.
"""

import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

SCHEMA = 1
TIMED_OUT = 124
GRACE = 3.0  # seconds a SIGTERMed group gets before SIGKILL


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "task"


def result_file(folder: Path, name: str) -> Path:
    return folder / f"{slug(name)}.json"


def stamp(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch(text: str) -> float:
    return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp()


def read(folder: Path, name: str) -> dict | None:
    try:
        rec = json.loads(result_file(folder, name).read_text())
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("schema") == SCHEMA else None


def write(folder: Path, name: str, rec: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    final = result_file(folder, name)
    tmp = final.with_name(f".{final.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"schema": SCHEMA, **rec}, indent=1) + "\n")
    os.replace(tmp, final)


def alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":  # os.kill(pid, 0) would terminate the process there
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate(pid: int, is_alive=alive, sleep=time.sleep, grace: float = GRACE) -> None:
    """The runner's whole process group: SIGTERM, a grace, SIGKILL for what is left (taskkill /T /F on Windows)."""
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    waited = 0.0
    while is_alive(pid) and waited < grace:
        sleep(0.1)
        waited += 0.1
    try:
        os.killpg(pid, signal.SIGKILL)  # stragglers of the group, also when the leader already went
    except (ProcessLookupError, PermissionError):
        pass


def detach_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)}
    return {"start_new_session": True}


def start(folder: Path, name: str, cmds: list[str], top: str, main: str, limit: int, now: float,
          spawn=subprocess.Popen) -> dict:
    """Write the `starting` record, then launch the runner detached; a runner that cannot start leaves a failed
    `done` record for the next tick to evaluate."""
    rec = {"task": name, "state": "starting", "pid": 0, "started": stamp(now), "ended": None, "limit": limit,
           "cmds": cmds, "top": top, "main": main, "exit": None, "output": "", "consumed": False}
    write(folder, name, rec)
    argv = [sys.executable, str(Path(__file__).resolve()), "run", str(result_file(folder, name))]
    try:
        spawn(argv, cwd=main, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              **detach_kwargs())
    except OSError as e:
        rec = {**rec, "state": "done", "ended": stamp(now), "exit": 1, "output": f"could not start the runner: {e}"}
        write(folder, name, rec)
    return rec


def status(rec: dict | None, now: float, is_alive=alive) -> str:
    """none | running | overdue (past its limit, still going) | dead (the runner is gone without a result) |
    finished (a done result no tick has evaluated) | consumed."""
    if not rec:
        return "none"
    if rec["state"] == "done":
        return "consumed" if rec.get("consumed") else "finished"
    if now - epoch(rec["started"]) > rec["limit"]:
        return "overdue"
    if rec["pid"] > 0 and not is_alive(rec["pid"]):
        return "dead"
    return "running"


def finish(folder: Path, name: str, rec: dict, ok: bool, why: str, now: float, code: int | None = None,
           consumed: bool = False) -> dict:
    rec = {**rec, "state": "done", "ended": stamp(now), "exit": code if code is not None else (0 if ok else 1),
           "output": "" if ok else why[-1500:], "consumed": consumed}
    write(folder, name, rec)
    return rec


def consume(folder: Path, name: str, rec: dict) -> None:
    write(folder, name, {**rec, "consumed": True})


def run(path: Path) -> int:
    """The runner: mark the record running with this pid, run the Check, write the result."""
    import tasks  # here: tasks imports this module
    rec = json.loads(path.read_text())
    folder, name = path.parent, rec["task"]
    write(folder, name, {**rec, "state": "running", "pid": os.getpid()})
    try:
        ok, why = tasks.run_check(rec["cmds"], rec["top"], rec["main"], rec["limit"])
    except BaseException as e:  # a crash is a failed check with its reason, never a silent hang
        ok, why = False, f"the runner crashed: {type(e).__name__}: {e}"
    cur = read(folder, name) or rec
    finish(folder, name, {**cur, "pid": os.getpid()}, ok, why, time.time())
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "run":
        sys.exit(run(Path(sys.argv[2])))
    sys.exit("usage: task_detach.py run <result file>")
