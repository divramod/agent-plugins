"""The files below a plan of the one plan shape (hal2 plan 0376, design A1), the Python twin of hal2-core's
`plan_shape::subplan` and `plan_shape::step`: a sub-plan's `subplan.md` (kind Subplan: its deliverable, wave,
schedule and who runs it; its status derived and written only by the generator), a work sub-plan's
`steps/step-NN.md` (kind Plan Step, where a status is set) and 99-uat's (kind UAT Step, one check whose status follows
its verdict). Each parses to its typed keys, the unknown keys kept, and renders back canonically.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import shape_names as names
from shape_front import Fields, Writer
from shape_names import ShapeError

SUBPLAN = "Subplan"
PLAN_STEP = "Plan Step"
UAT_STEP = "UAT Step"


def _plan(f: Fields) -> int:
    plan = f.number("plan")
    if plan is None:
        raise f.error("needs `plan`")
    return plan


def _status(f: Fields, words: tuple[str, ...]) -> str:
    status = f.parsed("status", lambda w: names.word(words, w))
    if status is None:
        raise f.error("needs `status`")
    return status


@dataclass
class Subplan:
    title: str
    description: str
    status: str
    plan: int
    wave: int | None = None
    schedule: str | None = None
    touches: list[str] = field(default_factory=list)
    who: str | None = None
    run: str | None = None
    shotfile: str | None = None
    landed: str | None = None
    rest: list = field(default_factory=list)
    body: str = ""

    @classmethod
    def parse(cls, file: str, text: str) -> "Subplan":
        f, body = Fields.read(file, text, SUBPLAN)
        wave = f.number("wave")
        if wave == 0:
            raise f.error("`wave` starts at 1")
        return cls(title=f.required("title"), description=f.required("description"),
                   status=_status(f, names.SUBPLAN), plan=_plan(f), wave=wave,
                   schedule=f.parsed("schedule", lambda w: names.word(names.SCHEDULE, w)),
                   touches=f.list("touches"), who=f.text("who"), run=f.text("run"), shotfile=f.text("shotfile"),
                   landed=f.text("landed"), rest=f.rest, body=body)

    def render(self) -> str:
        return (Writer(SUBPLAN).quoted("title", self.title).quoted("description", self.description)
                .text("status", self.status).number("plan", self.plan).some_number("wave", self.wave)
                .some("schedule", self.schedule).list("touches", self.touches).some("who", self.who)
                .some("run", self.run).some("shotfile", self.shotfile).some("landed", self.landed)
                .rest(self.rest).finish(self.body))


@dataclass
class PlanStep:
    title: str
    description: str
    status: str
    plan: int
    subplan: int
    wave: int | None = None
    touches: list[str] = field(default_factory=list)
    model: str | None = None
    effort: str | None = None
    window: str | None = None
    size: str | None = None
    why: str | None = None
    was: str | None = None
    rest: list = field(default_factory=list)
    body: str = ""
    uat = False

    @classmethod
    def parse(cls, file: str, text: str) -> "PlanStep":
        f, body = Fields.read(file, text, PLAN_STEP)
        title, description = f.required("title"), f.required("description")
        status, plan = _status(f, names.STEP), _plan(f)
        subplan = f.number("subplan")
        if subplan is None:
            raise f.error("needs `subplan`")
        return cls(title=title, description=description, status=status, plan=plan, subplan=subplan,
                   wave=f.number("wave"), touches=f.list("touches"), model=f.text("model"),
                   effort=f.text("effort"), window=f.text("window"), size=f.text("size"), why=f.text("why"),
                   was=f.text("was"), rest=f.rest, body=body)

    def render(self) -> str:
        return (Writer(PLAN_STEP).quoted("title", self.title).quoted("description", self.description)
                .text("status", self.status).number("plan", self.plan).number("subplan", self.subplan)
                .some_number("wave", self.wave).list("touches", self.touches).some("model", self.model)
                .some("effort", self.effort).some("window", self.window).some("size", self.size)
                .some("why", self.why).some("was", self.was).rest(self.rest).finish(self.body))


@dataclass
class UatStep:
    title: str
    description: str
    status: str
    plan: int
    check: str
    priority: str
    kind: str
    tags: list[str] = field(default_factory=list)
    verdict: str | None = None
    rest: list = field(default_factory=list)
    body: str = ""
    uat = True

    @classmethod
    def parse(cls, file: str, text: str) -> "UatStep":
        f, body = Fields.read(file, text, UAT_STEP)
        title, description = f.required("title"), f.required("description")
        status, plan = _status(f, names.STEP), _plan(f)
        check, priority = f.required("check"), f.required("priority")
        tags, kind, verdict = f.list("tags"), f.required("kind"), f.text("verdict")
        if status not in names.UAT_STEP:
            raise ShapeError(f"{file}: a UAT step is never `{status}`")
        if verdict is not None:
            try:
                names.verdict_status(verdict)
            except ShapeError as error:
                raise ShapeError(f"{file}: {error}") from error
        return cls(title=title, description=description, status=status, plan=plan, check=check,
                   priority=priority, kind=kind, tags=tags, verdict=verdict, rest=f.rest, body=body)

    def render(self) -> str:
        return (Writer(UAT_STEP).quoted("title", self.title).quoted("description", self.description)
                .text("status", self.status).number("plan", self.plan).text("check", self.check)
                .text("priority", self.priority).list("tags", self.tags).text("kind", self.kind)
                .some("verdict", self.verdict).rest(self.rest).finish(self.body))


def parse_step(file: str, text: str, uat: bool) -> PlanStep | UatStep:
    """A step of 99-uat (`uat`) or of a work sub-plan."""
    return UatStep.parse(file, text) if uat else PlanStep.parse(file, text)
