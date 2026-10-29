"""`/gp` where the farm's commits are neutral (hal2 plan 0409 D15, step 11): a Conventional head with a unit scope or
none, never a plan scope; no `Worktree:`/`Plan:`/`Step:` trailers; the plan link goes into the plan store instead
(`hal2-cli-plans link-commit --next`, before the commit; its post-commit hook links the new commit). Asked of the
plan skill's planread.py (`neutral(root)`: False without `hal.farm`, no process); a script copied outside a skills unit
has no planread and is always off, as before."""
import re
import sys
from pathlib import Path

PLAN_SCOPE = re.compile(r"^(?P<type>[a-z]+)\(\d[^)]*\)(?P<bang>!?):")
PLAN_NAME = re.compile(r"^\d{4}-[a-z0-9][a-z0-9-]*$")


def planread():
    """The plan skill's planread module, or None outside a skills unit."""
    if "planread" in sys.modules:
        return sys.modules["planread"]
    try:
        here = Path(__file__).resolve()
        unit = next(p for p in here.parents if (p / ".claude-plugin").is_dir())
        sys.path.insert(0, str(unit / "scripts"))
        try:
            from skillpath import load
        finally:
            sys.path.pop(0)
        return load("plan", "planread", __file__)
    except Exception:
        return None


def pointer(root: str, name: str) -> str:
    """The checkout's plan pointer `name` (CURRENT_PLAN): the git dir's, else plans/<name>, through the plan skill's
    pointers.py; the plans/ file alone outside a skills unit. Stripped, "" for none."""
    try:
        here = Path(__file__).resolve()
        unit = next(p for p in here.parents if (p / ".claude-plugin").is_dir())
        sys.path.insert(0, str(unit / "scripts"))
        try:
            import skillpath
        finally:
            sys.path.pop(0)
        return skillpath.pointers(__file__).read(root, name)
    except Exception:
        file = Path(root, "plans", name)
        return file.read_text().strip() if file.is_file() else ""


def neutral(root: str) -> bool:
    found = planread()
    return bool(found and found.neutral(root))


def head(subject: str) -> str:
    """`feat(0409|3): x` -> `feat: x`: a plan scope (it starts with a digit) is dropped, any other scope stays."""
    return PLAN_SCOPE.sub(lambda m: f"{m['type']}{m['bang']}:", subject, count=1)


def link(root: str, plan: str, step: str) -> None:
    """The next commit links to the plan (a `<NNNN>-<slug>` only) and step in the store; never fails."""
    found = planread()
    if found and PLAN_NAME.match(plan or ""):
        found.link_next(root, plan, step or None)
