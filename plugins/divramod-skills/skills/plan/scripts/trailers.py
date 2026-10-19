"""`plan.py trailers <n>`: the origin trailers of a step's commit (hal2 plan 0355, D2); `plan.py scope [<n>]`: its
subject's scope (hal2 plan 0391, D22).

The commit's subject is `<type>(<NNNN>|<step>): <what was done>` (a plan of a masterplan `<master>|<plan>|<step>`, plan
work that is no step `<NNNN>`); where it came from also stands in the last paragraph,
before `Co-Authored-By:`: `Worktree: <NN>`, `Plan: <NNNN>-<slug>`, `Step: <n>/<total>` (the step's number of all steps).
The coordinator pastes the three lines. A step that is no row of the plan's table is refused.
"""
from pathlib import Path


class TrailerError(Exception):
    pass


def worktree(root: Path) -> str:
    """The worktree's name: the folder's (`05` of `~/.hal/git/worktree/hal2/05`, `farmer-hal2`)."""
    return root.resolve().name


def lines(root: Path, slug: str, numbers: list[str], step: str) -> list[str]:
    """The three trailer lines of `step` in the plan `slug` whose step table numbers are `numbers`."""
    step = step.strip()
    if step not in numbers:
        raise TrailerError(f"step {step!r} is no row of plan {slug}: {', '.join(numbers) or 'no steps'}")
    return [f"Worktree: {worktree(root)}", f"Plan: {slug}", f"Step: {step}/{len(numbers)}"]


def scope(slug: str, parent: int | None, numbers: list[str], step: str = "") -> str:
    """The subject scope of plan `slug`: `<NNNN>|<step>`, `<master>|<NNNN>|<step>` when its `parent` is a masterplan,
    without a step the plan alone."""
    head = slug[:4] if parent is None else f"{parent:04d}|{slug[:4]}"
    step = step.strip()
    if not step:
        return head
    if step not in numbers:
        raise TrailerError(f"step {step!r} is no row of plan {slug}: {', '.join(numbers) or 'no steps'}")
    return f"{head}|{step}"
