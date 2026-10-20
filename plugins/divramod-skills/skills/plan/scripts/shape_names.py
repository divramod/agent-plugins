"""The names and statuses of the one plan shape (hal2 plan 0376, design A2 and §3 A6), the Python twin of
hal2-core's `plan_shape::refs` and `plan_shape::status`.

A sub-plan's folder is `NN-<slug>` (01-98, `99-uat` the last), a step's file `step-NN.md` (`step-NNN.md` in a
converted sub-plan over 99 steps), a step's ref `<sub-plan>.<step>`, `01.03`; numbered on, never renumbered. A step's
status is written in its file, the only place a status is set; a sub-plan's and a plan's are derived from the steps
below them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

UAT_NUMBER = 99
UAT_FOLDER = "99-uat"

STEP = ("open", "next", "running", "blocked", "done", "dropped")
UAT_STEP = ("open", "done", "blocked", "dropped")
SUBPLAN = ("open", "running", "blocked", "done")
PLAN = ("open", "uat", "done", "abandoned")
SCHEDULE = ("serial", "waves")
KIND_NAMES = {STEP: "StepStatus", SUBPLAN: "SubplanStatus", PLAN: "PlanStatus", SCHEDULE: "Schedule"}
VERDICTS = {"pass": "done", "skip": "done", "fail": "blocked", "blocked": "blocked"}


class ShapeError(ValueError):
    """Why a text or a folder is not of the plan shape."""


def word(words: tuple[str, ...], text: str) -> str:
    """`text` as one of `words` (a status or schedule); anything else is an error naming the legal ones."""
    found = text.strip()
    if found not in words:
        raise ShapeError(f"`{found}` is no {KIND_NAMES.get(words, 'status')} status: {', '.join(words)}")
    return found


def finished(status: str) -> bool:
    """Done or dropped: nothing is left to do in the step."""
    return status in ("done", "dropped")


def subplan_status(steps: list[str], uat: bool) -> str:
    """A sub-plan's status from its steps': `done` when every step is done or dropped (no step at all: done for
    99-uat, open for a work sub-plan); `blocked` when a step is blocked and none next or running; `running` when a
    step is next, running or done; else `open`."""
    if not steps:
        return "done" if uat else "open"
    if all(finished(s) for s in steps):
        return "done"
    if "blocked" in steps and not any(s in ("next", "running") for s in steps):
        return "blocked"
    if any(s in ("next", "running", "done") for s in steps):
        return "running"
    return "open"


def plan_status(written: str | None, work: list[str], uat: str | None) -> str:
    """A plan's status from its sub-plans': `abandoned` stays when written so; `done` when every sub-plan is done;
    `uat` when every work sub-plan is done and 99-uat is not; else `open` (`uat` None: the plan has no 99-uat)."""
    if written == "abandoned":
        return "abandoned"
    if not all(s == "done" for s in work):
        return "open"
    return "uat" if uat is not None and uat != "done" else "done"


def verdict_status(verdict: str) -> str:
    """The status a UAT step's verdict sets: pass and skip `done`, fail and blocked `blocked`."""
    if verdict not in VERDICTS:
        raise ShapeError(f"`{verdict}` is no verdict: pass, fail, skip, blocked")
    return VERDICTS[verdict]


@dataclass(frozen=True, order=True)
class SubplanId:
    """A sub-plan's folder name, `01-records`."""
    number: int
    slug: str

    @classmethod
    def parse(cls, folder: str) -> "SubplanId":
        bad = ShapeError(f"`{folder}` is no sub-plan folder `NN-<slug>`")
        found = re.fullmatch(r"(\d{2})-([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)", folder)
        if not found:
            raise bad
        number, slug = int(found.group(1)), found.group(2)
        if number == 0 or (number == UAT_NUMBER and slug != "uat"):
            raise bad
        return cls(number, slug)

    def is_uat(self) -> bool:
        return self.number == UAT_NUMBER

    def __str__(self) -> str:
        return f"{self.number:02d}-{self.slug}"


def step_number(file: str) -> int:
    """A step's number from its file name, `step-02.md` -> 2."""
    found = re.fullmatch(r"step-(\d{2,3})\.md", file)
    if not found or int(found.group(1)) == 0:
        raise ShapeError(f"`{file}` is no step file `step-NN.md`")
    return int(found.group(1))


def step_file(number: int, wide: bool = False) -> str:
    """The file name of step `number`, `step-03.md`; `wide` (a sub-plan over 99 steps) writes three digits."""
    return f"step-{number:03d}.md" if wide else f"step-{number:02d}.md"


@dataclass(frozen=True, order=True)
class StepRef:
    """A step's ref, `01.03`: its sub-plan's number and its own."""
    subplan: int
    step: int

    @classmethod
    def parse(cls, text: str) -> "StepRef":
        found = re.fullmatch(r"(\d{1,3})\.(\d{1,3})", text.strip())
        if not found or int(found.group(1)) == 0 or int(found.group(2)) == 0:
            raise ShapeError(f"`{text}` is no step ref `<sub-plan>.<step>`")
        return cls(int(found.group(1)), int(found.group(2)))

    def __str__(self) -> str:
        return f"{self.subplan:02d}.{self.step:02d}"


def resolve(text: str, only: int | None) -> StepRef:
    """`text` as a ref: `01.03` as written; a bare step number (`3`) in the one work sub-plan `only` names (the
    plan's single work sub-plan, or the one plans/LEAD names); without it the bare number is ambiguous."""
    text = text.strip()
    if "." in text:
        return StepRef.parse(text)
    if not re.fullmatch(r"\d+", text) or int(text) == 0:
        raise ShapeError(f"`{text}` is no step ref or number")
    if only is None:
        raise ShapeError(f"step `{text}` is ambiguous: the plan has several work sub-plans, write "
                         f"`<sub-plan>.{int(text):02d}`")
    return StepRef(only, int(text))
