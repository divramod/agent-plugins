"""The one handoff resolver (plan 0592's D13): where a session's handoff lives, by its role.

    a role with a role folder   roles/<role>/handoff.md   farmer, tollman (their `$FARMER_DIR` in a test), steward,
                                                          mayor, lord, pope
    a plan                      plans/<plan>/handoff.md   a foreman's current plan in the record format (the handoff
                                                          skill's where.py: the store home's edit folder too)
    a servant, no plan          the root HANDOFF.md       gitignored; a legacy plan's too

The old places are read as a fallback, in order, when the new one does not exist: the root `HANDOFF.md` (the steward's
and every role's before D13), the farmer's `owner-handoff.md`. `resolve` gives

    {file, form: role | record | legacy, found, exists, fallbacks, plan, decisions, questions}

`file` the place a new handoff goes, `found` the file to read (the first that exists: `file`, then the fallbacks),
paths absolute.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402

sys.path.insert(0, str(sibling("handoff") / "scripts"))
import where  # noqa: E402  (the handoff skill's: a plan's handoff, either home)

ROOT_FILE = "HANDOFF.md"
ROLE_FOLDER = ("farmer", "tollman", "steward", "mayor", "lord", "pope")
STATE_OVERRIDE = "FARMER_DIR"  # the farmer skill's test override of the role state folders (roles.state_dir)
OLD = {"farmer": ("roles/farmer/owner-handoff.md", ROOT_FILE)}


def role_dir(root: Path, role: str, main: str | None) -> Path:
    """The role's folder: `roles/<role>/` of its checkout, or its state folder under `$FARMER_DIR` (farmer, tollman)."""
    override = os.environ.get(STATE_OVERRIDE)
    if override and role in ("farmer", "tollman"):
        base = Path(override) / Path(main or root).name
        return base if role == "farmer" else base / role
    return root / "roles" / role


def absolute(root: Path, name: str | None) -> str | None:
    return str(name if Path(name).is_absolute() else root / name) if name else None


def resolve(root: str | Path, role: str | None, main: str | None = None) -> dict:
    """The handoff of the session with `role` in the checkout `root`."""
    root = Path(root).resolve()
    if role in ROLE_FOLDER:
        file = role_dir(root, role, main) / "handoff.md"
        fallbacks = [root / name for name in OLD.get(role, (ROOT_FILE,))]
        found = {"file": str(file), "form": "role", "plan": None, "decisions": None, "questions": None}
    else:
        located = where.locate(root)
        found = {key: absolute(root, located.get(key)) for key in ("file", "plan", "decisions", "questions")}
        found["form"] = located["form"]
        fallbacks = [root / ROOT_FILE] if located["form"] == "record" else []
    first = next((str(p) for p in [Path(found["file"]), *fallbacks] if p.is_file()), None)
    return {**found, "found": first, "exists": first == found["file"], "fallbacks": [str(p) for p in fallbacks]}
