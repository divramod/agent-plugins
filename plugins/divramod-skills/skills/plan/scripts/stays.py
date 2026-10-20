"""stays.py: `plan.py new` and `use` in an occupied field (hal2 plan 0376, D2, D4, D13; design §5 A10).

- `new` there adds a sub-plan to the current plan (schema 2) and keeps CURRENT_PLAN: `{"added": "subplan", "plan":
  "<current>", "subplan": "03-<slug>"}`. A current plan of schema 1 or a masterplan has no sub-plans: refused (exit 1)
  with the hint. `--no-current` writes a separate plan and touches nothing; `--here` is the user's switch (the old
  value into plans/PREVIOUS_PLAN).
- `use` there is refused the same way; `use --here` switches as `new --here`.
"""
from __future__ import annotations

from pathlib import Path

import occupied
import shape_new
from shape_names import ShapeError


class Refused(Exception):
    pass


def switch(root: Path, target: str) -> None:
    try:
        occupied.switch_here(root, target)
    except ValueError as error:
        raise Refused(str(error)) from None


def guard_new(root: Path, args) -> dict | None:
    """What `new` does in an occupied field: None to go on (a free field, `--no-current`, `--here` after it kept the
    old value), the sub-plan's JSON when it added one; raises Refused when neither is possible."""
    if args.no_current:
        return None
    found = occupied.of(root)
    if found is None:
        return None
    if args.here:
        return None  # new_plan switches; the caller kept the old value through `keep_here`
    flags = [f for f in ("research", "masterplan", "parallel") if getattr(args, f, False)]
    flags += [f for f in ("spec", "parent", "seed") if getattr(args, f, "")]
    if flags or found["schema"] != 2:
        why = ("a plan of schema 1 has no sub-plans" if found["schema"] != 2 else
               f"--{flags[0]} makes a plan of its own, not a sub-plan")
        raise Refused(occupied.refuse_text(found, f"new: {why}"))
    try:
        added = shape_new.add_subplan(root, root / "plans" / found["plan"], args.title, args.goal)
    except ShapeError as error:
        raise Refused(str(error)) from None
    return {"added": "subplan", "plan": found["plan"], "subplan": added["subplan"]}


def guard_use(root: Path, target: str, here: bool) -> None:
    """`use <target>`: refused in an occupied field unless it names the current plan; `--here` keeps the old one."""
    found = occupied.of(root)
    if found is None or found["plan"] == target:
        return
    if not here:
        raise Refused(occupied.refuse_text(found, f"use {target}"))
    switch(root, target)
