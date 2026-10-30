"""The prune duty's plan of /prune, asked off the round (hal2 plan 0480 step 04.01, D4; research 0117 #3).

/prune's `plan --json --cached-sizes` took up to PLAN_TIMEOUT a round (55.7 s on average, 95 of 422 rounds at the cap).
The round now starts it detached (`prune.py ask`, one at a time, its pid in ASK_FILE, its stderr in ASK_LOG) and reads
the result a round later from PLAN_FILE, `{schema, at, data, why}`, written atomically by the ask (`at`: when it
started, the time of its facts). A plan older than PLAN_MAX_AGE, or asked before the last /prune run started, is not
used: that round plans nothing and asks again. The holds (busy.py's workqueue hold, the train's local phase) are
checked live (`held`, prune.building), never read from the plan; /prune's run proves each field again before each
action (executor.recheck), so a plan one round old never deletes unsaved work.
"""

import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PLAN_FILE, ASK_FILE, ASK_LOG = "prune-plan.json", "prune-ask.json", "prune-ask.log"
SCHEMA = 1
PLAN_TIMEOUT = 120  # the ask uses --cached-sizes (no walk, plan 0377 D26); the detached run measures and fills the cache
PLAN_MAX_AGE = 20 * 60  # the duty is due every 15 minutes (roles/tollman/ROLE.md): the last round's plan, with slack
ASK_MAX_AGE = PLAN_TIMEOUT + 60  # an ask ends at its own timeout: a pid file older than this is a dead ask's
BUSY_TIMEOUT = 30  # busy.py asks hal2-cli-workqueue with 20 s


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def utc(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


def epoch(text: str) -> float:
    return dt.datetime.fromisoformat(text).timestamp()


def write_json(path: Path, value: dict) -> None:
    """Atomic: a reader sees the old file or the new one, never half of it."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value))
    tmp.replace(path)


def ask(script: Path, main: str, timeout: int = PLAN_TIMEOUT) -> tuple[dict | None, str]:
    """/prune's `plan --json` of the farm, synchronously: (its `{plan, facts}`, ""), or (None, why not)."""
    argv = [sys.executable, str(script), "plan", "--json", "--cached-sizes", "--repo", main]
    try:
        p = subprocess.run(argv, cwd=main, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"prune.py plan: {e}"
    if p.returncode:
        return None, f"prune.py plan exited {p.returncode}: {(p.stderr or p.stdout).strip()[-300:]}"
    try:
        data = json.loads(p.stdout)
        data["plan"]["jobs"], data["facts"]["fields"], data["facts"]["disk"]
    except (ValueError, KeyError, TypeError):
        return None, "prune.py plan --json gave no plan"
    return data, ""


def save(folder: Path, at: float, data: dict | None, why: str) -> None:
    write_json(folder / PLAN_FILE, {"schema": SCHEMA, "at": utc(at), "data": data, "why": why})


def load(folder: Path, since: float = 0.0, now: float | None = None) -> tuple[dict | None, str] | None:
    """The last ask's (data, why), or None: none, unreadable, past PLAN_MAX_AGE or asked before `since` (the last run's
    start: its facts are from before the run changed the farm)."""
    try:
        rec = json.loads((folder / PLAN_FILE).read_text())
        at = epoch(rec["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if (now or time.time()) - at > PLAN_MAX_AGE or at < since:
        return None
    data, why = rec.get("data"), str(rec.get("why") or "")
    return (data, why) if data is not None or why else None


def asking(folder: Path, now: float | None = None) -> bool:
    """Does an ask this duty started still live (its pid, no older than ASK_MAX_AGE)?"""
    try:
        info = json.loads((folder / ASK_FILE).read_text())
        return alive(int(info["pid"])) and (now or time.time()) - epoch(info["at"]) < ASK_MAX_AGE
    except (OSError, ValueError, KeyError, TypeError):
        return False


def begin(folder: Path, argv: list[str], cwd: str, spawn=subprocess.Popen) -> int:
    """The ask started detached (its own session, stdin and stdout closed, stderr in ASK_LOG); its pid kept."""
    with (folder / ASK_LOG).open("w") as err:
        p = spawn(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                  start_new_session=True)
    write_json(folder / ASK_FILE, {"schema": SCHEMA, "pid": p.pid, "at": utc(time.time()), "argv": argv})
    return p.pid


def held(busy_script: Path, main: str) -> str | None:
    """/prune's own answer, live (busy.py run as a program, plan 0377 D3: never imported): `deferred: train building
    (hold ...)` while a workqueue hold stands, else None (also when it cannot be asked, as busy.py counts it)."""
    try:
        p = subprocess.run([sys.executable, str(busy_script), "--repo", main], cwd=main, capture_output=True,
                           text=True, timeout=BUSY_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return (p.stdout.strip() or None) if p.returncode == 0 else None
