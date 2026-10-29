"""occupied.py: a field whose CURRENT_PLAN pointer names a started plan is occupied (hal2 plan 0376, D2, D4, D5, D13).

Occupied = the plan is `open`: schema 2 by shape's derived status, schema 1 and legacy plans have a step not done, a
masterplan a row not done (`uat`, `done` and `abandoned` are not occupied, D15). A fresh plan counts: it is `open` from
the moment it is current, so no free check may call its field free. Nothing but the plan's own end (`plan.py leave`)
or the user's `--here` changes the file; `--here` keeps the old value in the gitignored `plans/PREVIOUS_PLAN` (D4),
which `leave` restores when it is still unfinished (D5).

Imports no plan.py (that runs as `__main__`); the plan and spec skills call it with the repository root.
"""
from __future__ import annotations

from pathlib import Path

import masterplan
import planhome
import pointers
import shape
import table

POINTER = pointers.CURRENT_PLAN  # the pointers' names: their files are the git dir's, else plans/ (pointers.py)
PREVIOUS = pointers.PREVIOUS_PLAN
HINT = ("`--here` only on the user's words (it keeps {plan} in plans/PREVIOUS_PLAN); work for another field: "
        "`create.py --lead \"<field> <plan> <NN-slug>\"` in a servant field, or `--no-current` for a separate plan")


def name_in(root: Path, name: str) -> str:
    return pointers.read(root, name)


def plan_file(root: Path, ref: str) -> Path | None:
    """plans/<ref>/plan.md for a slug `ref`, else None (a shot, a task, a spec folder, a missing plan)."""
    if not masterplan.SLUG.match(ref):
        return None
    path = planhome.plans_dir(root) / ref / masterplan.MAIN  # the store home's view (planhome.py), else plans/
    return path if path.is_file() else None


def status_of(path: Path) -> str:
    """`open`, `uat`, `done` or `abandoned` for the plan at `path`; a plan with nothing left open is `done`."""
    folder, text = path.parent, masterplan.read(path)
    written = masterplan.key(text, "status")
    if written == "abandoned":
        return "abandoned"
    if shape.is_shape(folder):
        return shape.load(folder).derived(written)
    if written in masterplan.FINISHED:
        return str(written)
    lines = text.split("\n")
    found = table.header(lines)
    if found is None:
        return "done"
    at, cols = found
    open_rows = [c for _, c in table.rows(lines, at) if not c[cols["status"]].lower().startswith("done")]
    return "open" if open_rows else "done"


def of(root: Path) -> dict | None:
    """The occupied current plan as {plan, status, schema}, else None."""
    ref = name_in(root, POINTER)
    path = plan_file(root, ref)
    if path is None or status_of(path) != "open":
        return None
    return {"plan": ref, "status": "open", "schema": 2 if shape.is_shape(path.parent) else 1}


def refuse_text(found: dict, what: str) -> str:
    return f"{what}: this field is occupied by {found['plan']}; " + HINT.format(plan=found["plan"])


def check_here(root: Path, target: str = "") -> dict | None:
    """`--here`'s refusal, before anything is written (a new plan claimed): PREVIOUS_PLAN keeps another unfinished
    plan already. The occupied current plan `switch_here` would keep, None when there is none to keep."""
    found = of(root)
    if found is None or found["plan"] == target:
        return None
    kept = name_in(root, PREVIOUS)
    if kept and (path := plan_file(root, kept)) is not None and status_of(path) == "open" and kept != found["plan"]:
        raise ValueError(f"the PREVIOUS_PLAN pointer already keeps {kept}, still unfinished: finish it or `plan.py "
                         "leave` first; a second --here would lose it")
    return found


def switch_here(root: Path, target: str) -> None:
    """`--here` (D4): keep the occupied current plan in the PREVIOUS_PLAN pointer before CURRENT_PLAN names
    `target`."""
    found = check_here(root, target)
    if found is not None:
        pointers.write(root, PREVIOUS, found["plan"])


def restore_previous(root: Path) -> str | None:
    """What `leave` does before deleting (D5): the unfinished plan in plans/PREVIOUS_PLAN becomes current again and
    the file goes; a finished or missing one is just deleted. Returns the restored slug."""
    kept = name_in(root, PREVIOUS)
    if not pointers.exists(root, PREVIOUS):
        return None
    pointers.remove(root, PREVIOUS)
    path = plan_file(root, kept)
    if path is None or status_of(path) != "open":
        return None
    pointers.write(root, POINTER, kept)
    return kept
