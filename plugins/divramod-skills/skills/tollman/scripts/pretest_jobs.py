"""The pretest's processes (hal2 plan 0349 step 28, D75): the gate's `list` and `plan` and its jobs, each in a process
group of its own, so a timeout, a red or the end of the landing's process stops all of it, a cargo build a gate
call started included. POSIX only, like engine.spawn (process groups, killpg).

A job runs as merge-to-main.yml's gate action runs it (.github/actions/gate/action.yml): `gate/main.sh <job>` from the
field's root with the plan entry's packages and targets and the range in its environment, and HAL2_GATE_NO_INSTALL
(gate/tools.sh: `need` installs nothing on the user's Mac, it prints `gate: tool missing: <tool>` and fails). Its
end: 0 green; the tool marker in its output, or a signal no one here sent: skipped; any other code red.
"""

import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path

POLL = 0.1
TOOL = "gate: tool missing:"


def environment(entry: dict, base: str, head: str) -> dict:
    """What merge-to-main.yml's gate action exports for a job, and the gate's switch that installs nothing."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HAL_CHANGED_", "HAL_GATE_", "HAL_PACKAGE_"))}
    for key, name in (("packages", "HAL_CHANGED_PACKAGES"), ("targets", "HAL_CHANGED_TARGETS")):
        if entry.get(key, "*") != "*":
            env[name] = entry[key]
    return {**env, "HAL_GATE_BASE": base, "HAL_GATE_HEAD": head, "HAL2_GATE_NO_INSTALL": "1"}


def stop(p: subprocess.Popen) -> None:
    """A process's whole group: TERM, then KILL after two seconds."""
    for sig, wait in ((signal.SIGTERM, 2), (signal.SIGKILL, 5)):
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):
            break
        try:
            p.wait(wait)
            return
        except subprocess.TimeoutExpired:
            continue
    with contextlib.suppress(subprocess.TimeoutExpired):
        p.wait(1)  # reaped, also when its group was gone already


def call(argv: list[str], cwd: str, timeout: float) -> tuple[int, str, str]:
    """A gate call in its own group: its code, stdout and stderr; at the timeout (or any interruption) the whole
    group is stopped and the exception goes on."""
    with subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, start_new_session=True) as p:
        try:
            out, err = p.communicate(timeout=timeout)
        except BaseException:
            stop(p)
            raise
    return p.returncode, out, err


def start(top: str, gate: Path, e: dict, base: str, head: str, row: dict) -> subprocess.Popen | None:
    """The job's process in a group of its own, its output in its row's file; None: it cannot start (why in row)."""
    try:
        with row["out"].open("w") as out:
            return subprocess.Popen(["bash", str(gate), e["job"]], cwd=top, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=subprocess.STDOUT, env=environment(e, base, head), start_new_session=True)
    except OSError as err:
        row["why"] = f"cannot start: {err}"
        return None


def output(row: dict) -> str:
    try:
        return row["out"].read_text(errors="replace")
    except OSError:
        return ""


def finished(row: dict, code: int, seconds: float) -> str:
    """A job's end in its row (the module doc); its name when it is red."""
    tools = [line.strip() for line in output(row).splitlines() if line.strip().startswith(TOOL)]
    if code < 0 or (code and tools):
        row.update(seconds=seconds, why=f"killed by signal {-code} from outside" if code < 0 else "; ".join(tools))
        return ""
    row.update(state="run", seconds=seconds, result="red" if code else "green", why=f"exit {code}" if code else "")
    return row["job"] if code else ""


def run_jobs(top: str, gate: Path, todo: list[dict], base: str, head: str, deadline: float, parallel: int,
             scratch: Path, groups: dict | None = None, progress: dict | None = None) -> list[dict]:
    """Each entry of `todo` as a gate job: its row {job, key, state, seconds, result, why, out}, at most `parallel`
    at once, a job whose group ({job: group}) has one running waiting for it. The first red stops the rest; the
    deadline stops all; whatever ends this (an exception, SIGTERM as SystemExit) stops every job still running.
    `progress["red"]` names the red job as soon as it is known."""
    groups, progress = groups or {}, progress if progress is not None else {}
    rows = {e["job"]: {"job": e["job"], "key": e.get("key"), "state": "skipped", "seconds": 0, "result": None,
                       "why": "the budget ended before it started", "out": scratch / f"{e['job']}.log"} for e in todo}
    waiting, running, red, stopped = list(todo), {}, "", "the pretest ended while it ran"
    try:
        while True:
            for job, (p, began) in list(running.items()):
                if (code := p.poll()) is not None:
                    del running[job]
                    ended = finished(rows[job], code, round(time.monotonic() - began, 1))
                    red = red or ended
            if red:
                progress["red"] = red
            if red or time.monotonic() >= deadline:
                stopped = f"stopped: {red} is red" if red else "the budget ended while it ran"
                for e in waiting if red else []:
                    rows[e["job"]]["why"] = f"not started: {red} is red"
                break
            busy = {groups[j] for j in running if j in groups}
            while len(running) < parallel and (free := [e for e in waiting if groups.get(e["job"]) not in busy]):
                e = free[0]
                waiting.remove(e)
                busy |= {groups[e["job"]]} if e["job"] in groups else set()
                if p := start(top, gate, e, base, head, rows[e["job"]]):
                    running[e["job"]] = (p, time.monotonic())
            if not running and not waiting:
                break
            time.sleep(POLL)
    finally:
        for job, (p, began) in running.items():
            stop(p)
            rows[job].update(seconds=round(time.monotonic() - began, 1), why=stopped)
    return [rows[e["job"]] for e in todo]
