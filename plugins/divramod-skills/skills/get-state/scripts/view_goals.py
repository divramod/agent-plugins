"""The mayor's, lord's and pope's view (hal2 plan 0366, D11): only their goals, from their own place's
`office/goals/` (mayor `1-year.md`, lord `3-5-years.md`, pope `life.md`). Read-only: the file is never created."""

import time
from pathlib import Path

import role as roles

GOALS = {
    "mayor": ("1-year.md", "Goals for the next year"),
    "lord": ("3-5-years.md", "Goals for the next 3 to 5 years"),
    "pope": ("life.md", "Life goals"),
}


def goals_path(who: str) -> Path:
    """Where the role's goals live: `<place>/office/goals/<file>`."""
    return Path(roles.place(who)) / "office" / "goals" / GOALS[who][0]


def goal_items(text: str) -> list[str]:
    """The file's `- ` lines; a nested line keeps its depth as non-breaking spaces (two per indent step)."""
    items = []
    for line in text.splitlines():
        body = line.lstrip(" \t")
        if not body.startswith("- "):
            continue
        indent = line[: len(line) - len(body)].replace("\t", "    ")
        items.append(" " * (len(indent) // 2 * 2) + body[2:].strip())
    return [i for i in items if i.strip(" ")]


def view(data: dict, ctx: dict) -> tuple[str, list[dict]]:
    """The title and one section holding the role's goals, else the empty state naming the file."""
    from views import title_of  # late: views imports this module

    who = ctx["role"]
    path = goals_path(who)
    heading = GOALS[who][1]
    try:
        text, mtime = path.read_text(encoding="utf-8"), path.stat().st_mtime
    except (OSError, UnicodeDecodeError):
        text, mtime = "", None
    items = goal_items(text)
    if not items:
        empty = f"No goals written yet. They would live in {path}"
        return title_of(ctx), [{"heading": heading, "items": [], "empty": empty}]
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
    return title_of(ctx), [{"heading": heading, "items": items},
                           {"heading": "Source", "text": f"{path} (changed {stamp})"}]
