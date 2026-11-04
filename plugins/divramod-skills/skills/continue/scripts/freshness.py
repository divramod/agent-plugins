"""Whether `/continue` restocks the field first (plan 0592's D16): `/mfm` runs only when the field is behind
`origin/main` and is neither hitched, landing nor paused (a hitched field stays on its head, a landing owns its
checkout, a paused field is the user's). Only a foreman's and a servant's field restock; the yard, the farmer's and
the tollman's checkouts keep their own ways.

    decide(root, role, field) -> {run: bool, why, behind: int | None}

Reads `git rev-list --count HEAD..origin/main` (the caller fetches first), `hal2-cli-git worktree queue --json` and
`worktree paused --json`; a CLI that cannot say counts as nothing queued or paused (the CLIs' own guards stay).
"""

from pathlib import Path

import clis

FIELD_ROLES = ("foreman", "servant")


def behind(root: str | Path, base: str = "origin/main") -> int | None:
    out = clis.git(root, "rev-list", "--count", f"HEAD..{base}")
    return int(out) if out and out.isdigit() else None


def ticket(root: str | Path, field: str) -> dict | None:
    """The field's merge queue ticket, None without one."""
    doc = clis.run_json("git", ["worktree", "queue", "--json"], root) or {}
    rows = doc.get("queue") if isinstance(doc.get("queue"), list) else []
    return next((t for t in rows if isinstance(t, dict) and t.get("slot") == field), None)


def paused(root: str | Path, field: str) -> dict | None:
    doc = clis.run_json("git", ["worktree", "paused", "--json"], root) or {}
    rows = doc.get("fields") if isinstance(doc.get("fields"), list) else []
    return next((r for r in rows if isinstance(r, dict) and str(r.get("field")) == field), None)


def queue_why(t: dict) -> str:
    if t.get("holding") or t.get("landing") or t.get("state") in ("active", "landing", "held"):
        return "its landing runs or holds the merge queue: the landing owns the checkout"
    if t.get("ready"):
        return "it is hitched: the field stays on its head until the train brings it in"
    return "it waits in the merge queue: the landing merges main itself"


def decide(root: str | Path, role: str | None, field: str | None) -> dict:
    if role not in FIELD_ROLES or not field:
        return {"run": False, "why": f"no restock for the {role or 'unknown'} role's checkout", "behind": None}
    count = behind(root)
    if not count:
        why = "up to date with origin/main" if count == 0 else "origin/main unknown (no remote ref)"
        return {"run": False, "why": why, "behind": count}
    if (t := ticket(root, field)) is not None:
        return {"run": False, "why": queue_why(t), "behind": count}
    if (p := paused(root, field)) is not None:
        return {"run": False, "why": f"paused by {p.get('by') or '?'}: only the farmer resumes it", "behind": count}
    return {"run": True, "why": f"{count} commits behind origin/main", "behind": count}
