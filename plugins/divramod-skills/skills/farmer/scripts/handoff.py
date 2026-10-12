"""The farmer's handoff before its clear (hal2 plan 0132): what the session knows goes into `handoff.md` in its state
folder (`roles/farmer/` of the farmer slot, never a committed HANDOFF.md: the farmer commits nothing of its branch but
roles/farmer/ROLE.md and the folder's .gitignore), then the session starts hal2's clear-and-continue itself, which waits for the turn to end, types
`/clear` and then `/farmer act`. `/farmer act` and `/farmer start` read handoff.md first.
"""

import datetime as dt
import json
from pathlib import Path

import deliver
import mtm_scan
import wake

TEMPLATE = """# farmer handoff (<repo>, <date time>)

## The user's decisions (do not ask again)

## The merge queue and its holds

## Merge trains

## Open threads (questions to peers, promised messages, what each waits for)

## Pauses and priorities (with reasons)

## Next
"""


def path(main: str) -> Path:
    """handoff.md; the owner skill's `owner-handoff.md` becomes it once."""
    d = mtm_scan.state_dir(main)
    new, old = d / "handoff.md", d / "owner-handoff.md"
    if old.exists() and not new.exists():
        old.rename(new)
    return new


def show(main: str) -> str:
    f = path(main)
    if f.exists():
        return f"handoff: {f}"
    return f"handoff: {f} (missing: write it with these sections)\n\n{TEMPLATE}"


def fresh(main: str, now: dt.datetime) -> str | None:
    """None when handoff.md was written for this handoff (after the pending one was asked for, else within
    HANDOFF_TIMEOUT), else why not."""
    f = path(main)
    if not f.exists():
        return f"{f} is missing: write it first"
    written = dt.datetime.fromtimestamp(f.stat().st_mtime)
    pending = wake.read(main).get("handoff")
    since = dt.datetime.fromisoformat(pending["at"]) if pending else now - wake.HANDOFF_TIMEOUT
    return None if written >= since else f"{f} is older than this handoff ({since:%H:%M}): write it first"


def clear(top: str, main: str, now: dt.datetime) -> tuple[int, str]:
    """Start the clear-and-continue of the farmer session once handoff.md is written: (exit code, what happened)."""
    why = fresh(main, now)
    if why:
        return 1, why
    pane = wake.farmer_pane(top)
    if not pane:
        return 1, "no farmer session"
    session = (deliver.agent(pane) or {}).get("session_id")
    args = ["clear-and-continue", "--pane", pane, "--prompt", wake.ACT, "--without-plan", "--detach", "--json"]
    code, out = deliver.cli(*args, *(["--session", session] if session else []))
    try:
        result = json.loads(out)
    except json.JSONDecodeError:
        result = {"status": "error", "message": out.strip() or f"exit {code}"}
    started = code == 0 or result.get("reason") == "already-running"
    what = (f"clear-and-continue started: /clear, then {wake.ACT}" if started else
            f"clear-and-continue refused: {result.get('reason') or result.get('message') or code}")
    mtm_scan.log(main, {"kind": "handoff-clear", "slot": "farmer", "what": what, "note": "", "by": "farmer",
                        "do": "wake"})
    return (0 if started else 1), what
