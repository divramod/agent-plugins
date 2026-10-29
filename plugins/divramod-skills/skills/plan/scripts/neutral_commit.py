"""`plan.py trailers` and `scope` where the farm's commits are neutral (hal2 plan 0409 D15, step 11): a commit's head is a
Conventional head with a unit scope or none (never a plan scope) and its message carries no `Worktree:`, `Plan:`,
`Step:` trailers. The plan link goes into the plan store instead: `trailers` records the plan and step the next commit
links to (`hal2-cli-plans link-commit --next`, planread.link_next) and prints nothing; `scope` prints nothing, so the
commit writer uses a unit scope or none. Where the switch is off (planread.neutral: hal2 itself, every farm without the
setting) both commands print what they always did."""
from pathlib import Path

import planread


def trailers(root: Path, lines: list[str]) -> bool:
    """When neutral: the next commit links to the plan and step named by the trailer `lines` (`Plan: <slug>`, `Step:
    <n>/<total>`); True, and the caller prints nothing. False when the switch is off (the caller prints the lines)."""
    if not planread.neutral(root):
        return False
    found = {line.partition(": ")[0]: line.partition(": ")[2] for line in lines}
    planread.link_next(root, found.get("Plan", ""), found.get("Step") or None)
    return True


def scope(root: Path) -> bool:
    """Whether `scope` prints nothing: the farm's commits are neutral (no plan scope in a head)."""
    return planread.neutral(root)
