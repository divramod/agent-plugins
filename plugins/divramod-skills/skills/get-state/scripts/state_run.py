"""A field's plan run state and its workqueue wait, for the state table and the pages (hal2 plan 0514, D4, D7).

- `run_state(path)` reads the field's `PLAN_STATE` file through the plan skill's own reader (`runstate.read`; no copy of
  the format): {state, why, at} for the plan the field's CURRENT_PLAN names, else None.
- `wait_of(status, path, is_main)` reads a field's wait out of ONE `hal2-cli-workqueue status --json` document (read
  once per run, `state_sources.workqueue_status`): a job or hold of the field that waits names what it waits behind
  (`waits behind landing 07`), a frozen run names the hold that froze it. A field is matched by its worktree folder
  (`<repo>/<NN>`, the workqueue's own field name) or by the job's cwd, never by a name prefix (D16).
- `phrase(row)` is the State cell's words for both: `pushing, waits behind landing 07`, `waiting (the answer)`.

Pure apart from the one file read; a missing plan skill, file or document gives None, never an error.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import load, pointers as _pointers  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

_pointers(__file__)  # runstate.py imports the plan skill's `pointers` by its bare name: load it first
try:
    runstate = load("plan", "runstate", __file__)
except Exception:  # noqa: BLE001  (a broken plan skill never fails the report)
    runstate = None


def run_state(path: str | Path) -> dict | None:
    """{state, why, at} of the plan the checkout's CURRENT_PLAN names; None without a file, a stale or a bad one."""
    if runstate is None:
        return None
    try:
        found = runstate.read(path)
    except Exception:  # noqa: BLE001
        return None
    return {k: found[k] for k in ("state", "why", "at")} if found else None


def field_name(path: str | Path, is_main: bool = False) -> str:
    """The workqueue's name for the checkout: `<repo>/<NN>` for a worktree, the folder's name for the main checkout."""
    p = Path(path)
    return p.name if is_main else f"{p.parent.name}/{p.name}"


def _mine(job: dict, path: str, name: str) -> bool:
    """The job runs in the field: its `field` is the field's name, or its cwd lies inside the field's folder."""
    if job.get("field") == name:
        return True
    cwd = job.get("cwd")
    return bool(cwd) and (os.path.realpath(cwd) + os.sep).startswith(os.path.realpath(path) + os.sep)


def _tail(field: str) -> str:
    return field.rsplit("/", 1)[-1] or "?"


def _label(item: dict) -> str:
    return f"{item.get('class') or 'job'} {_tail(item.get('field') or '')}"


def wait_of(status: dict | None, path: str | Path, is_main: bool = False) -> str | None:
    """`waits behind landing 07` for a field with a waiting job or hold, `frozen by smuggle 07` for a frozen run, else
    None (also for an unknown document)."""
    if not isinstance(status, dict):
        return None
    path, name = str(path), field_name(path, is_main)
    rows = lambda key: [r for r in status.get(key) or [] if isinstance(r, dict)]  # noqa: E731
    holds = rows("holds")
    for frozen in rows("frozen"):
        if _mine(frozen, path, name):
            by = next((h for h in holds if h.get("id") == frozen.get("hold")), None)
            return f"frozen by {_label(by)}" if by else "frozen"
    waiting = [j for j in rows("waiting") if _mine(j, path, name)]
    waiting += [h for h in holds if h.get("state") == "waiting" and _mine(h, path, name)]
    if not waiting:
        return None
    holder = next((h for h in holds if h.get("state") == "holding" and not _mine(h, path, name)), None)
    holder = holder or next((j for j in rows("running") if not _mine(j, path, name)), None)
    return f"waits behind {_label(holder)}" if holder else "waits in the workqueue"


def phrase(row: dict) -> str:
    """The run state and the workqueue wait as the State cell says them; empty for neither. `pushing` carries the wait
    in its own phrase, any other state names the wait beside it."""
    run, wait = row.get("run_state"), row.get("wq_wait")
    out = []
    if run:
        word = run["state"] + (f" ({run['why']})" if run.get("why") else "")
        out.append(f"{word}, {wait}" if wait and run["state"] == "pushing" else word)
        wait = None if run["state"] == "pushing" else wait
    if wait:
        out.append(wait)
    return "; ".join(out)
