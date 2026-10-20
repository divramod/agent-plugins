"""field_free.py: the tests' way to call `plan.py new` or `use` again in one temp repository (hal2 plan 0376 row 9).

Since a started plan stays its field's current plan, a second `new` there adds a sub-plan or is refused. Tests that
build several plans one after the other free the field first, as a landing's `leave` does; tests of the stays-current
rules (test_stays.py) never call it.
"""
from __future__ import annotations

from pathlib import Path

import occupied


def free(root: Path, args) -> None:
    """Delete plans/CURRENT_PLAN when `args` is a `new` or `use` that would meet an occupied field."""
    args = list(args)
    if args[:1] not in (["new"], ["use"]) or "--no-current" in args or "--here" in args:
        return
    if (Path(root) / "plans" / "LEAD").is_file():
        return  # a servant's field: the refusal is what the test looks at
    if occupied.of(Path(root)) is not None:
        (Path(root) / occupied.POINTER).unlink()
