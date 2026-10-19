"""The farmer's handoff before its clear (hal2 plan 0132): what the session knows goes into `handoff.md` in its state
folder (`roles/farmer/` of the farmer's worktree, never a committed HANDOFF.md: the farmer commits nothing of its branch but
roles/farmer/ROLE.md and the folder's .gitignore), then the session starts hal2's clear-and-continue itself, which waits for the turn to end, types
`/clear` and then `/farmer act`. `/farmer act` and `/farmer start` read handoff.md first.

Another role's handoff (hal2 plan 0294) is the same with its `roles.Wiring`: handoff.md in its own state folder,
its own session cleared and continued with its own act command.

`## DO FIRST` (hal2 plan 0383 rule 7, D8) is the handoff's first section: what the fresh session does before any wake
item. `act` prints it inline and closes every wake item created before the handoff's last write (`written`, the
file's mtime): whoever wrote the handoff had seen them. The stamp is the mtime, not a line the model types, so it
stays right when the old handoff is archived and moved (plan 0383 step 9, D9).

A rewrite (`handoff --rewrite`, step 9, D9) first moves the old handoff.md to `handoff-archive/<UTC time>.md` beside
it (the state folder is gitignored, so the archive is runtime state): the new file is written from the template
with only what is in force, history stays in the archive, and a written handoff over `MAX_LINES` lines is warned about.
"""

import datetime as dt
import json
import sys
from pathlib import Path

import deliver
import due
import mtm_scan
import roles
import wake

MAX_LINES = 80
ARCHIVE = "handoff-archive"

TEMPLATE = """# farmer handoff (<repo>, <date time>)

## DO FIRST

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


def written(main: str, wiring: roles.Wiring = roles.FARMER) -> float | None:
    """The handoff's last write (its mtime as an epoch), None without a handoff.md."""
    f = path(main, wiring)
    return f.stat().st_mtime if f.exists() else None


def do_first(main: str, wiring: roles.Wiring = roles.FARMER) -> str:
    """The text of the handoff's `## DO FIRST` section, "" when there is none or it is empty."""
    f = path(main, wiring)
    lines, found = [], False
    for line in (f.read_text().splitlines() if f.exists() else []):
        if line.startswith("## "):
            if found:
                break
            found = line.strip().lower() == "## do first"
        elif found:
            lines.append(line)
    return "\n".join(lines).strip()


def show(main: str, wiring: roles.Wiring = roles.FARMER) -> str:
    f = path(main, wiring)
    if f.exists():
        return f"handoff: {f}"
    template = TEMPLATE.replace("# farmer handoff", f"# {wiring.role} handoff", 1)
    return f"handoff: {f} (missing: write it with these sections)\n\n{template}"


def archive(main: str, now: dt.datetime, wiring: roles.Wiring = roles.FARMER) -> Path | None:
    """Move the old handoff.md to `handoff-archive/<UTC time>.md` beside it; None when there is none. The move keeps
    the old file's mtime, so the next write is the only thing `written` ever sees."""
    f = path(main, wiring)
    if not f.exists():
        return None
    d = f.parent / ARCHIVE
    d.mkdir(exist_ok=True)
    stamp = now.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target, n = d / f"{stamp}.md", 1
    while target.exists():
        target, n = d / f"{stamp}-{n}.md", n + 1
    f.rename(target)
    return target


def rewrite(main: str, now: dt.datetime, wiring: roles.Wiring = roles.FARMER) -> str:
    """Archive the old handoff.md and show the template for the new one (what is in force only)."""
    old = archive(main, now, wiring)
    kept = f"the old handoff is in {old} (history only; write what is in force)\n" if old else ""
    return f"{kept}{show(main, wiring)}"


def length_warning(main: str, wiring: roles.Wiring = roles.FARMER) -> str | None:
    """A warning when handoff.md passes MAX_LINES lines: it must hold only what is in force."""
    f = path(main, wiring)
    n = len(f.read_text().splitlines()) if f.exists() else 0
    return (f"warning: {f} has {n} lines (over {MAX_LINES}): keep only what is in force, the archive keeps history"
            if n > MAX_LINES else None)


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
    if long := length_warning(main, wiring):
        print(long, file=sys.stderr)
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
