"""What the steward's page reads from outside the rows (hal2 plan 0366 D9): the daybook's open chores and the open
UAT checks. Read-only: the daybook is parsed from its day file (never `daybook.py show`, which writes), each source
degrades to None (unknown) or [] (nothing open) and never raises.
"""

import datetime as dt
import importlib.util
import os
import re
import sys
from pathlib import Path

import state_sources as src

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

DAY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
OPEN_STATES = ("untested", "fail", "retest", "blocked")
CHORE_ROLES = ("today", "later")


def load(name: str):
    """A module of the daybook skill's scripts by path (own module name, so no sibling's `farm` is shadowed); None when missing."""
    try:
        path = sibling("daybook", __file__) / "scripts" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"get_state_daybook_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except (FileNotFoundError, AttributeError, ImportError, OSError, SyntaxError):
        return None


def day_file(folder: Path, today: dt.date) -> tuple[Path, str] | None:
    """Today's day file, else the newest earlier one (a carry-over not made yet); (path, its date) or None."""
    days = sorted(m.group(1) for p in (folder.iterdir() if folder.is_dir() else []) for m in [DAY_RE.match(p.name)]
                  if m and m.group(1) <= today.isoformat())
    return (folder / f"{days[-1]}.md", days[-1]) if days else None


def chores(main: str, today: dt.date | None = None) -> dict | None:
    """`{"date", "items": [(section, text), ...]}`: the open `- [ ]` items of the day file's Today and Later sections,
    in file order; None when the daybook skill is missing, the folder has no day file or the file cannot be read."""
    farm, dayfile = load("farm"), load("dayfile")
    if farm is None or dayfile is None:
        return None
    found = day_file(Path(farm.folder_of(main)[0]), today or dt.date.today())
    if found is None:
        return None
    try:
        day = dayfile.parse(found[0].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    items = [(sec["role"], dayfile.OPEN_RE.sub("", item[0]).strip()) for sec in day["sections"] if sec["role"] in CHORE_ROLES
             for item in sec["items"] if dayfile.is_open(item)]
    return {"date": found[1], "items": items}


def open_uats(main: str) -> list[dict] | None:
    """The plans with checks still to run, from ONE `hal2-cli-plans uat list --json`: `{"plan", "title", "open" (count),
    "failed" (fail, retest and blocked), "next" (the first open check's `<key> <title>`)}`; None when the tool gives nothing."""
    raw = src.tool_json(["hal2-cli-plans", "uat", "list", "--json"], main)
    if isinstance(raw, dict):  # {"uats": [...]} since hal2 plan 0318; a bare list before
        raw = raw.get("uats")
    if not isinstance(raw, list):
        return None
    out = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        todo = [c for c in p.get("checks") or [] if (c.get("status") or {}).get("state") in OPEN_STATES]
        if not todo:
            continue
        bad = sum((c["status"]["state"] != "untested") for c in todo)
        first = todo[0]
        out.append({"plan": p.get("slug"), "title": p.get("title"), "open": len(todo), "failed": bad,
                    "next": f"{first.get('key')} {(first.get('check') or {}).get('title') or ''}".strip()})
    return out
