"""plan.md's generated overview (hal2 plan 0376, design A3 and A4), the Python twin of hal2-core's
`plan_shape::overview`, held byte-equal to it on the golden fixture (test_shape.py): between
`<!-- generated: overview -->` and `<!-- /generated -->` under `## Overview`, a table of the sub-plans (99-uat
included), a blank line, then the work steps in the old step table's columns, which every step table reader keeps
reading. `regenerate` is the one writer of everything derived: the block, plan.md's `status` and each sub-plan's.
"""
from __future__ import annotations

import envelope
import shape_names as names
from shape_names import ShapeError, StepRef

BEGIN = "<!-- generated: overview -->"
END = "<!-- /generated -->"
CELL = 200
PLAN_FILE = "plan.md"
SUBPLAN_HEADER = "| Sub-plan | Wave | Deliverable | Steps | Status |\n|---|---|---|---|---|\n"
STEP_HEADER = ("| # | Step | Done when | Model | Effort | Window | Size | Status |\n"
               "|---|---|---|---|---|---|---|---|\n")


def cell(text: str) -> str:
    """A cell: cut to 200 characters with `…`, a `|` written `\\|`."""
    text = text.strip()
    if len(text) > CELL:
        text = text[:CELL - 1] + "…"
    return text.replace("|", "\\|")


def row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |\n"


def subplan_row(sub) -> str:
    done, total = sub.counts()
    return row([f"[{sub.id.number:02d} {cell(sub.doc.title)}]({sub.file})",
                "-" if sub.doc.wave is None else str(sub.doc.wave), cell(sub.doc.description),
                f"{done}/{total}", sub.derived()])


def step_rows(sub) -> str:
    out = ""
    for step in sub.steps:
        doc = step.doc
        if doc.uat:
            continue
        opt = lambda value: "" if value is None else cell(value)
        out += row([str(StepRef(sub.id.number, step.number)), f"[{cell(doc.title)}]({step.file})",
                    cell(doc.description), opt(doc.model), opt(doc.effort), opt(doc.window), opt(doc.size),
                    doc.status])
    return out


def render(shape) -> str:
    """The block's text: the sub-plan table, a blank line, the work step table."""
    out = SUBPLAN_HEADER + "".join(subplan_row(sub) for sub in shape.subplans)
    return out + "\n" + STEP_HEADER + "".join(step_rows(sub) for sub in shape.work())


def conflict(line: str) -> bool:
    return line.startswith("<<<<<<< ") or line.startswith(">>>>>>> ") or line == "======="


def block(file: str, text: str) -> tuple[int, int]:
    """Where the block's text starts (after BEGIN) and where END starts."""
    at = text.find(BEGIN)
    if at < 0:
        raise ShapeError(f"{file} has no `{BEGIN}` line")
    start = at + len(BEGIN)
    end = text.find(END, start)
    if end < 0:
        raise ShapeError(f"{file} has no `{END}` line after `{BEGIN}`")
    return start, end


def written(file: str, text: str) -> str:
    """The block's text as written (without its markers)."""
    start, end = block(file, text)
    return text[start:end].removeprefix("\n")


def replace(file: str, text: str, new: str) -> str:
    """`text` with its block replaced by `new`. Refused: no markers, or a merge conflict outside them, which writing
    the block would hide (one inside is resolved by writing it)."""
    start, end = block(file, text)
    outside = text[:start - len(BEGIN)].splitlines() + text[end:].splitlines()
    if any(conflict(line) for line in outside):
        raise ShapeError(f"{file} holds a merge conflict outside its generated overview")
    return text[:start] + "\n" + new + text[end:]


def written_status(text: str) -> str:
    """plan.md's written status; an error when it is none of the plan statuses."""
    try:
        front, _ = envelope.split(text)
        meta = envelope.parse(front or "")
    except envelope.FormatError as error:
        raise ShapeError(str(error)) from error
    status = meta.get("status")
    try:
        return names.word(names.PLAN, "" if status is None else str(status))
    except ShapeError as error:
        raise ShapeError(f"{PLAN_FILE}: {error}") from error


def with_status(file: str, text: str, word: str) -> str:
    """`text` with its front matter's `status:` line set to `word`."""
    front, _ = envelope.split(text)
    if front is None:
        raise ShapeError(f"{file}: no front matter")
    out, found = "---\n", False
    for line in front.splitlines(keepends=True):
        if not found and line.startswith("status:"):
            out += f"status: {word}\n"
            found = True
        else:
            out += line
    if not found:
        raise ShapeError(f"{file}: no `status:` line")
    return out + text[len("---\n") + len(front):]


def regenerate(plan_md: str, shape) -> list[tuple[str, str]]:
    """Every file the derivation changes, `(path, new text)`: plan.md (its overview and `status`, `abandoned` kept)
    first, then each `subplan.md` whose written status is not its derived one. Empty when all is current."""
    changed = []
    for sub in shape.subplans:
        derived = sub.derived()
        if sub.doc.status != derived:
            doc = sub.copy_doc()
            doc.status = derived
            changed.append((sub.file, doc.render()))
    status = shape.derived(written_status(plan_md))
    text = with_status(PLAN_FILE, replace(PLAN_FILE, plan_md, render(shape)), status)
    if text != plan_md:
        changed.insert(0, (PLAN_FILE, text))
    return changed
