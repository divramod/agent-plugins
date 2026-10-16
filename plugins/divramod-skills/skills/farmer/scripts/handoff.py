"""The farmer's handoff before its clear (hal2 plan 0132): what the session knows goes into `handoff.md` in its state
folder (`roles/farmer/` of the farmer's worktree, never a committed HANDOFF.md: the farmer commits nothing of its branch but
roles/farmer/ROLE.md and the folder's .gitignore), then the session starts hal2's clear-and-continue itself, which waits for the turn to end, types
`/clear` and then `/farmer act`. `/farmer act` and `/farmer start` read handoff.md first.

Another role's handoff (hal2 plan 0294) is the same with its `roles.Wiring`: handoff.md in its own state folder,
its own session cleared and continued with its own act command.
"""

import datetime as dt
import json
from pathlib import Path

import deliver
import due
import mtm_scan
import roles
import wake

TEMPLATE = """# farmer handoff (<repo>, <date time>)

## The user's decisions (do not ask again)

## The merge queue and its holds

## Merge trains

## Open threads (questions to peers, promised messages, what each waits for)

## Pauses and priorities (with reasons)

## Next
"""


def path(main: str, wiring: roles.Wiring = roles.FARMER) -> Path:
    """handoff.md; the owner skill's `owner-handoff.md` becomes it once."""
    d = mtm_scan.state_dir(main, wiring.role)
    new, old = d / "handoff.md", d / "owner-handoff.md"
    if old.exists() and not new.exists():
        old.rename(new)
    return new


def show(main: str, wiring: roles.Wiring = roles.FARMER) -> str:
    f = path(main, wiring)
    if f.exists():
        return f"handoff: {f}"
    template = TEMPLATE.replace("# farmer handoff", f"# {wiring.role} handoff", 1)
    return f"handoff: {f} (missing: write it with these sections)\n\n{template}"


def fresh(main: str, now: dt.datetime, wiring: roles.Wiring = roles.FARMER) -> str | None:
    """None when handoff.md was written for this handoff (after the pending one was asked for, else within
    HANDOFF_TIMEOUT), else why not."""
    f = path(main, wiring)
    if not f.exists():
        return f"{f} is missing: write it first"
    written = dt.datetime.fromtimestamp(f.stat().st_mtime)
    pending = wake.read(main, wiring).get("handoff")
    since = dt.datetime.fromisoformat(pending["at"]) if pending else now - wake.HANDOFF_TIMEOUT
    return None if written >= since else f"{f} is older than this handoff ({since:%H:%M}): write it first"


def session_effort(top: str, wiring: roles.Wiring) -> str:
    """The effort a role's session runs at (ROLE.md's `session_effort`, default high); an unreadable or invalid
    setting falls back to the default: the clear must still happen."""
    try:
        text = (Path(top) / wiring.role_file).read_text()
    except OSError:
        return due.SESSION_EFFORT
    value = due.schedule(text, wiring.duties)[1]["session_effort"]
    return value if value in due.EFFORTS else due.SESSION_EFFORT


def clear(top: str, main: str, now: dt.datetime, wiring: roles.Wiring = roles.FARMER) -> tuple[int, str]:
    """Start the clear-and-continue of the role's session once handoff.md is written: (exit code, what happened)."""
    why, role = fresh(main, now, wiring), wiring.role
    if why:
        return 1, why
    pane = wake.farmer_pane(top)
    if not pane:
        return 1, f"no {role} session"
    session = (deliver.agent(pane) or {}).get("session_id")
    args = ["clear-and-continue", "--pane", pane, "--prompt", wiring.act, "--without-plan", "--detach", "--json"]
    if wiring.session_effort:
        args += ["--effort", session_effort(top, wiring)]
    code, out = deliver.cli(*args, *(["--session", session] if session else []))
    try:
        result = json.loads(out)
    except json.JSONDecodeError:
        result = {"status": "error", "message": out.strip() or f"exit {code}"}
    started = code == 0 or result.get("reason") == "already-running"
    what = (f"clear-and-continue started: /clear, then {wiring.act}" if started else
            f"clear-and-continue refused: {result.get('reason') or result.get('message') or code}")
    mtm_scan.log(main, {"kind": "handoff-clear", "slot": role, "what": what, "note": "", "by": role, "do": "wake"},
                 role)
    return (0 if started else 1), what
