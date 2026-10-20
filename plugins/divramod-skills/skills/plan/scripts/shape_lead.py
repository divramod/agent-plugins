"""A servant's field of the one plan shape (hal2 plan 0376, design §4, A3, A8): its gitignored `plans/LEAD` holds
`<foreman's field> <plan slug> <NN-slug>`, the sub-plan the servant runs. There `plan.py status` writes only the step
files of that sub-plan and never regenerates plan.md's overview (the foreman does after the merge); every command
that writes plan.md, a subplan.md, the ledgers or 99-uat is refused. A third token of digits is the legacy step or
masterplan row form and keeps plan.py's old refusal (parallel.py, masterplan.servant_refusal).
"""
from __future__ import annotations

from pathlib import Path

import parallel
from shape_names import ShapeError, SubplanId

# What a sub-plan's servant may not do: everything that writes the foreman's files.
REFUSED = ("new", "subplan", "step", "assign", "uat", "grilled", "landing", "changelog", "scaffold", "run",
           "migrate", "leave", "convert")


def subplan_of(marker: dict | None) -> SubplanId | None:
    """The sub-plan a LEAD marker names (`02-cli`); None for no marker or the legacy digits form."""
    token = (marker or {}).get("step", "")
    if not token or token.isdigit():
        return None
    try:
        return SubplanId.parse(token)
    except ShapeError:
        return None


def marker(root: Path) -> dict | None:
    """The field's plans/LEAD (of `--root`, else of the cwd's checkout)."""
    return parallel.subservant_marker(root, Path.cwd())


def refusal(found: dict, command: str) -> str:
    return (f"this field is the servant of sub-plan {found['step']} of plan {found['plan']} for the foreman in "
            f"field {found['slot']}: `{command}` writes the foreman's files (plan.md, subplan.md, the ledgers, "
            f"99-uat). Mark only your sub-plan's steps (`plan.py status {found['step'][:2]}.<step> <status>`), commit "
            f"them and send the foreman one line when the sub-plan is done")


def refuse(found: dict, args) -> None:
    """Raise when `args` is a command a sub-plan's servant may not run."""
    command = args.command
    if command in REFUSED or (command == "overview" and getattr(args, "write", False)):
        raise ShapeError(refusal(found, command))


def lead(root: Path, plan_slug: str) -> SubplanId | None:
    """The sub-plan this field's servant runs in plan `plan_slug`; None outside a sub-plan servant's field. A LEAD
    of another plan is refused: the servant works only on its foreman's plan."""
    found = marker(root)
    sub = subplan_of(found)
    if sub is None:
        return None
    if found["plan"] != plan_slug:
        raise ShapeError(f"plans/LEAD names plan {found['plan']}, not {plan_slug}: a servant works only on its "
                         "foreman's plan")
    return sub
