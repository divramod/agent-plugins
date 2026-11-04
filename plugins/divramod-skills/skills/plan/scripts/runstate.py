"""runstate.py: a plan's run state, the one word that says what its field is doing (hal2 plan 0514, D2-D4).

The state lives in the gitignored per-field runtime file `PLAN_STATE`, beside `CURRENT_PLAN` (pointers.py: the git
dir's `hal/PLAN_STATE` in the store home, else `plans/PLAN_STATE`; never plan.md, so a running tool rewrites no tracked
file). JSON: {"schema": 1, "plan": "<NNNN-slug>", "state": ..., "why": ..., "at": "<UTC ISO, Z>"}.

    working   a step runs (`status <n> next` writes it)
    pushing   the plan's end pushes the branch (`plan.py end`; the pre-push hook can take minutes)
    waiting   the plan waits for something it names in `why` (needs `why`)
    blocked   the plan cannot go on, `why` says what is missing (needs `why`)
    done      every step is done, the end is not yet run (the last `status <n> done` writes it)
    hitched   the harvest is hitched for the tollman (frozen: no new steps)
    landed    the work is in the barn; `plan.py leave` then clears the file

    read(root)                       -> the state of the plan the pointer names, None for none, a bad or a stale file
    write(root, plan, state, why)    -> the dict written (atomic: temp file, then rename)
    clear(root)                      -> removes the file from both places
    after_status(root, ...)          -> the writes `plan.py status` makes; clear_stale(root) the one `plan.py leave` makes

Imports no plan.py (that runs as `__main__`); another skill loads this file by its path, never this folder on sys.path.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from pathlib import Path

import pointers

NAME = pointers.PLAN_STATE
SCHEMA = 1
STATES = ("working", "pushing", "waiting", "blocked", "done", "hitched", "landed")
NEEDS_WHY = ("waiting", "blocked")


class StateError(Exception):
    """A state that cannot be written; plan.py prints it as its own error."""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current(root: Path | str) -> str:
    return pointers.read(root, pointers.CURRENT_PLAN)


def read_any(root: Path | str) -> dict | None:
    """The file as written (a good one: JSON object, schema 1, a known state), whichever plan it names."""
    try:
        data = json.loads(pointers.path(root, NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("state") not in STATES:
        return None
    if not isinstance(data.get("plan"), str) or not data["plan"]:
        return None
    return {"schema": SCHEMA, "plan": data["plan"], "state": data["state"], "why": data.get("why") or "",
            "at": str(data.get("at") or "")}


def read(root: Path | str, plan: str | None = None) -> dict | None:
    """The run state of `plan` (default: the plan the checkout's CURRENT_PLAN names); None for no file, a bad one, or
    one that names another plan (a stale file never answers for the plan now current)."""
    found = read_any(root)
    want = current(root) if plan is None else plan
    return found if found is not None and want and found["plan"] == want else None


def write(root: Path | str, plan: str, state: str, why: str | None = None) -> dict:
    """Writes the state of `plan` where the home puts the pointers; the copy in the other place goes. Raises
    StateError for an unknown state, a `waiting` or `blocked` without a why, or no plan."""
    if not plan:
        raise StateError("no plan: the checkout has no CURRENT_PLAN")
    if state not in STATES:
        raise StateError(f"unknown state '{state}': one of {', '.join(STATES)}")
    why = (why or "").strip()
    if state in NEEDS_WHY and not why:
        raise StateError(f"state '{state}' needs --why: what the plan waits for or what is missing")
    data = {"schema": SCHEMA, "plan": plan, "state": state, "why": why, "at": now()}
    place = pointers.target(root, NAME)
    place.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=".PLAN_STATE.", dir=place.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(json.dumps(data, ensure_ascii=False) + "\n")
        os.replace(temp, place)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    other = pointers.tree_path(root, NAME)
    if other != place:
        other.unlink(missing_ok=True)
    elif (git := pointers.git_path(root, NAME)) is not None:
        git.unlink(missing_ok=True)  # never a stale copy that shadows the one written
    return data


def clear(root: Path | str) -> None:
    pointers.remove(root, NAME)


def clear_stale(root: Path | str) -> bool:
    """Removes a file that does not name the plan CURRENT_PLAN names now (the pointer was deleted or moved on); True
    when it did. A bad file goes too."""
    if not pointers.exists(root, NAME):
        return False
    if read(root) is not None:
        return False
    clear(root)
    return True


def after_status(root: Path | str, plan: str, status: str, finished: bool) -> dict | None:
    """What `plan.py status <n> <status>` on `plan` does to the file; `finished`: every step of the plan is done now.
    Only the plan the checkout works on counts (a foreman marking a servant's plan with --plan changes nothing).

    next -> working; done with the plan finished -> done; a reopened plan whose state is `done` -> working. Anything
    else leaves the file as it is. The dict written, else None."""
    if not plan or plan != current(root):
        return None
    word = status.strip().lower()
    if word.startswith("next"):
        return write(root, plan, "working")
    if word.startswith("done") and finished:
        return write(root, plan, "done")
    held = read(root, plan)
    if held is not None and held["state"] == "done" and not finished:
        return write(root, plan, "working")
    return None
