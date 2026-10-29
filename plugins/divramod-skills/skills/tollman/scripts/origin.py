"""The origin trailers of a commit the tollman writes (hal2 plan 0355, D2): `Worktree: <NN>` (a train: every car's
field, `Worktree: 02, 03, 27`) and, for a car on a plan, `Plan: <NNNN>-<slug>`. The subject says what changed; these
lines are the message's last paragraph, before any attribution. A plan name that is no `<NNNN>-<slug>` (a shot's
`<shotfile>/<n>/<title>`) has no `Plan:` line.

Where the farm's commits are neutral (hal2 plan 0409 D15, step 11; the plan skill's `planread.neutral(root)`: False
without `hal.farm`, so hal2 itself and every farm today are unchanged) a commit has no trailers: `trailers(...,
root=<checkout>)` is empty and `paragraph(root, ...)` is the `-m` arguments to add, none then (git would keep an empty
`-m ""` paragraph)."""
import re
import sys
from pathlib import Path

PLAN = re.compile(r"^\d{4}-[a-z0-9][a-z0-9-]*$")


def planread():
    """The plan skill's planread module (loaded once, by its path), or None outside a skills unit."""
    if "planread" in sys.modules:
        return sys.modules["planread"]
    try:
        unit = next(p for p in Path(__file__).resolve().parents if (p / ".claude-plugin").is_dir())
        sys.path.insert(0, str(unit / "scripts"))
        try:
            from skillpath import load
        finally:
            sys.path.pop(0)
        return load("plan", "planread", __file__)
    except Exception:
        return None


def neutral(root) -> bool:
    """The farm of the checkout `root` keeps its commits neutral (planread.neutral); False without a root."""
    found = planread() if root else None
    return bool(found and found.neutral(root))


def trailers(fields: list[str], plans: list[str] | tuple = (), root=None) -> str:
    """The trailer paragraph of the fields (in car order) and the plans among `plans` that are plan names; empty where
    the commits of the checkout `root` are neutral."""
    if neutral(root):
        return ""
    lines = ["Worktree: " + ", ".join(dict.fromkeys(fields))] if fields else []
    lines += [f"Plan: {p}" for p in dict.fromkeys(plans) if PLAN.match(p or "")]
    return "\n".join(lines)


def paragraph(root, fields: list[str], plans: list[str] | tuple = ()) -> list[str]:
    """The `-m <trailers>` arguments of a commit: none when the trailers are empty (never an empty `-m` paragraph)."""
    text = trailers(fields, plans, root)
    return ["-m", text] if text else []


YARD = "main"  # the yard (the main checkout's uncommitted work) is `main` in the landing's trailer too (hal2-git title.rs)
