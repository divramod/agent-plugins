"""`plan.py uat add <title>` on the one plan shape (hal2 plan 0376, design §1 A1, A7): one UAT check as the next step
file of `subplans/99-uat/steps/` (kind UAT Step: `check` `U<n>`, never reused; `priority`, `kind`, `tags`; uat.md's
check fields before the first `##`), status `open` until the landing writes its verdict; then the overview. A plan
of schema 1 keeps `plan.py uat`'s uat.md.
"""
from __future__ import annotations

import re
from pathlib import Path

import shape
import shape_new
import shape_names as sn
import planhome
from shape_docs import UatStep
from shape_names import ShapeError

PRIORITIES = ("p1", "p2", "p3")
KINDS = ("scripted", "explore")


def body(number: int, title: str, fields: dict) -> str:
    """The step's body: its title, then the check fields Open, Run, Steps and Expected."""
    out = f"\n# Step {number:02d}: {title}\n\n"
    if fields.get("open"):
        out += f"Open: {fields['open']}\n"
    if fields.get("run"):
        out += f"Run: `{fields['run']}`\n"
    if fields.get("steps"):
        out += "Steps:\n" + "".join(f"{n}. {step}\n" for n, step in enumerate(fields["steps"], 1))
    return out + f"\nExpected: {fields.get('expected') or title}\n"


def next_check(steps) -> int:
    """One above every number a check of 99-uat has had (its `check` `U<n>`, its step number)."""
    used = [s.number for s in steps] + [int(m.group(1)) for s in steps if (m := re.fullmatch(r"U(\d+)", s.doc.check))]
    return max(used, default=0) + 1


def add(root: Path, folder: Path, title: str, fields: dict) -> dict:
    """The next UAT step of the plan `folder`; `fields`: open, run, steps (a list), expected, priority, kind,
    tags."""
    if not title.strip():
        raise ShapeError("a UAT check needs a title")
    priority, kind = fields.get("priority") or "p2", fields.get("kind") or "scripted"
    if priority not in PRIORITIES or kind not in KINDS:
        raise ShapeError(f"priority is one of {', '.join(PRIORITIES)}, kind one of {', '.join(KINDS)}")
    expected = fields.get("expected") or title.strip()
    if len(expected) > 200:
        raise ShapeError(f"the expected result is {len(expected)} characters: a description is at most 200")
    uat = shape.load(folder).uat()
    if uat is None:
        raise ShapeError(f"{folder.name} has no `subplans/{sn.UAT_FOLDER}/`")
    number = max((s.number for s in uat.steps), default=0) + 1
    doc = UatStep(title=title.strip(), description=expected, status="open",
                  plan=shape_new.plan_id(folder), check=f"U{next_check(uat.steps)}", priority=priority, kind=kind,
                  tags=list(fields.get("tags") or []), body=body(number, title.strip(), fields))
    path = folder / Path(uat.file).parent / "steps" / sn.step_file(number)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc.render())
    return {"added": "uat", "plan": folder.name, "ref": str(sn.StepRef(sn.UAT_NUMBER, number)), "check": doc.check,
            "file": planhome.rel(path, root, posix=True), "overview": shape.write_overview(root, folder)}

