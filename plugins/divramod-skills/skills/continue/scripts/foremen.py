"""`/continue all`, the farmer's command (plan 0592's D18): the paused and unfinished foremen, oldest first.

    listing(main) -> [{field, path, plan, done, total, next, paused, last_commit, checked}]

From one `hal2-cli-git worktree list --json`: a numbered field (00-99) with an unfinished plan (`plan_progress`
done < total) and no agent running there, or a paused one; a servant's field (plans/LEAD) is its foreman's and left
out. Oldest first by the field's last commit, so the check of each resumed plan sees the adaptations of the ones
resumed before it. `checked` is when the field's last `/continue` passed its check (`continue.py checked`), so the
farmer starts the next only after it.
"""

import json
import re
import sys
from pathlib import Path

import clis

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import load  # noqa: E402

pointers = load("plan", "pointers")
FIELD = re.compile(r"^\d{2}$")
MARK = "hal/continue-checked.json"


def marker(root: str | Path) -> Path | None:
    """The checkout's own `<git-dir>/hal/continue-checked.json` (per worktree, never committed)."""
    found = clis.git(root, "rev-parse", "--git-path", MARK)
    return (Path(root) / found).resolve() if found and not Path(found).is_absolute() else Path(found) if found else None


def checked_at(root: str | Path) -> str | None:
    path = marker(root)
    try:
        return json.loads(path.read_text()).get("at") if path and path.is_file() else None
    except (OSError, ValueError):
        return None


def candidate(row: dict) -> dict | None:
    if row.get("main") or not FIELD.match(str(row.get("name") or "")):
        return None
    progress = row.get("plan_progress") if isinstance(row.get("plan_progress"), dict) else None
    unfinished = bool(progress) and int(progress.get("done") or 0) < int(progress.get("total") or 0)
    paused = row.get("paused") if isinstance(row.get("paused"), dict) else None
    if not (unfinished and (paused or not row.get("agents"))):
        return None
    if row.get("path") and pointers.exists(row["path"], pointers.LEAD):
        return None
    nxt = progress.get("next") if isinstance(progress.get("next"), dict) else {}
    return {"field": row["name"], "path": row.get("path"), "plan": row.get("plan") or progress.get("slug"),
            "done": progress.get("done"), "total": progress.get("total"),
            "next": f"{nxt.get('number')}: {nxt.get('title')}" if nxt else None,
            "paused": paused, "last_commit": row.get("last_commit") or 0,
            "checked": checked_at(row["path"]) if row.get("path") else None}


def listing(main: str | Path) -> list[dict] | None:
    """None when hal2 cannot list the fields."""
    doc = clis.run_json("git", ["worktree", "list", "--json"], main)
    rows = doc.get("worktrees") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return None
    found = [c for row in rows if isinstance(row, dict) if (c := candidate(row))]
    return sorted(found, key=lambda c: (c["last_commit"], c["field"]))
