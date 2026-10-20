"""The one plan shape (hal2 plan 0376, design §1-§3), the plan skill's Python model of it, the twin of hal2-core's
`plan_shape` (held byte-equal on the golden fixture `code/rust/libs/hal2-core/tests/golden/plan-shape/`,
test_shape.py).

A plan folder with `subplans/` is schema 2: its plan.md holds the generated overview, each sub-plan
`subplans/NN-<slug>/subplan.md` its steps `steps/step-NN.md`, the last sub-plan `99-uat` one UAT step per check. A
folder without `subplans/` is schema 1 or legacy and read as before (plan.py). Statuses live only in step files
(shape_names.py derives the rest); the front matter is read and written by shape_front.py and shape_docs.py, the
overview by shape_overview.py.

The overview is written by `hal2-cli-plans overview <plan> --write` when that binary has the command (`$HAL2_CLI_PLANS`,
else on PATH), else by shape_overview.py's own render: `write_overview` returns which one wrote it.
"""
from __future__ import annotations

import copy
import functools
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import shape_names as names
import shape_overview as overview
from shape_docs import Subplan, parse_step
from shape_names import ShapeError, StepRef, SubplanId

SUBPLANS = "subplans"
CLI_ENV = "HAL2_CLI_PLANS"
CLI_NAME = "hal2-cli-plans"
CLI_TIMEOUT = 30


@dataclass
class ShapeStep:
    number: int
    file: str
    doc: object


@dataclass
class ShapeSubplan:
    id: SubplanId
    file: str
    doc: Subplan
    steps: list[ShapeStep] = field(default_factory=list)

    def derived(self) -> str:
        return names.subplan_status([s.doc.status for s in self.steps], self.id.is_uat())

    def counts(self) -> tuple[int, int]:
        """How many of its steps are finished (done or dropped), and how many it has."""
        return sum(1 for s in self.steps if names.finished(s.doc.status)), len(self.steps)

    def copy_doc(self) -> Subplan:
        return copy.deepcopy(self.doc)


def part(path: str) -> tuple[str, str | None] | None:
    """(folder, None) for `subplans/<folder>/subplan.md`, (folder, file) for `subplans/<folder>/steps/step-*.md`,
    None for every other file (the ledgers, a sub-plan's handoff)."""
    if not path.startswith(SUBPLANS + "/"):
        return None
    folder, _, rest = path[len(SUBPLANS) + 1:].partition("/")
    if rest == "subplan.md":
        return folder, None
    file = rest.removeprefix("steps/")
    if file != rest and "/" not in file and file.startswith("step-"):
        return folder, file
    return None


@dataclass
class Shape:
    subplans: list[ShapeSubplan] = field(default_factory=list)

    @classmethod
    def from_files(cls, files) -> "Shape":
        """The shape of the files `(path, text)`, paths relative to the plan folder with `/`."""
        subplans: dict[int, ShapeSubplan] = {}
        steps = []
        for path, text in files:
            found = part(path)
            if found and found[1] is None:
                add_subplan(subplans, found[0], path, text)
            elif found:
                steps.append((found[0], found[1], path, text))
        for folder, file, path, text in steps:
            add_step(subplans, folder, file, path, text)
        ordered = [subplans[n] for n in sorted(subplans)]
        for sub in ordered:
            sub.steps.sort(key=lambda s: s.number)
        return cls(ordered)

    def work(self) -> list[ShapeSubplan]:
        return [s for s in self.subplans if not s.id.is_uat()]

    def uat(self) -> ShapeSubplan | None:
        return next((s for s in self.subplans if s.id.is_uat()), None)

    def subplan(self, number: int) -> ShapeSubplan | None:
        return next((s for s in self.subplans if s.id.number == number), None)

    def step(self, at: StepRef) -> ShapeStep | None:
        sub = self.subplan(at.subplan)
        return next((s for s in sub.steps if s.number == at.step), None) if sub else None

    def resolve(self, text: str, lead: int | None = None) -> StepRef:
        """`01.03`, or a bare `3` in the sub-plan plans/LEAD names (`lead`), else in the plan's only work sub-plan."""
        work = self.work()
        only = work[0].id.number if len(work) == 1 else None
        return names.resolve(text, only if lead is None else lead)

    def derived(self, written: str | None = None) -> str:
        """The plan's status from its sub-plans' (`written`: plan.md's, for `abandoned`)."""
        uat = self.uat()
        return names.plan_status(written, [s.derived() for s in self.work()], uat.derived() if uat else None)


def add_subplan(subplans: dict, folder: str, path: str, text: str) -> None:
    sid = SubplanId.parse(folder)
    if sid.number in subplans:
        raise ShapeError(f"sub-plans `{subplans[sid.number].id}` and `{sid}` share the number {sid.number:02d}")
    subplans[sid.number] = ShapeSubplan(sid, path, Subplan.parse(path, text))


def add_step(subplans: dict, folder: str, file: str, path: str, text: str) -> None:
    sid = SubplanId.parse(folder)
    sub = subplans.get(sid.number)
    if sub is None or sub.id != sid:
        raise ShapeError(f"{path}: its sub-plan has no `subplan.md`")
    number = names.step_number(file)
    if any(s.number == number for s in sub.steps):
        raise ShapeError(f"{path}: step {number:02d} is there twice")
    sub.steps.append(ShapeStep(number, path, parse_step(path, text, sid.is_uat())))


def is_shape(folder: Path) -> bool:
    """A plan folder of schema 2: it has `subplans/`."""
    return (folder / SUBPLANS).is_dir()


def files(folder: Path) -> list[tuple[str, str]]:
    """Every Markdown file below `subplans/`, `(path relative to the plan folder with /, text)`, sorted."""
    found = sorted((folder / SUBPLANS).rglob("*.md")) if is_shape(folder) else []
    return [(p.relative_to(folder).as_posix(), p.read_text()) for p in found if p.is_file()]


def load(folder: Path) -> Shape:
    """The shape of a plan folder of schema 2; an error naming the plan for one of schema 1 or legacy."""
    if not is_shape(folder):
        raise ShapeError(f"{folder.name} is not in the plan shape of schema 2 (no `{SUBPLANS}/`)")
    return Shape.from_files(files(folder))


@functools.lru_cache(maxsize=None)
def cli_has_overview(cli: str) -> bool:
    try:
        out = subprocess.run([cli, "overview", "--help"], capture_output=True, text=True, timeout=CLI_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0 and "--write" in out.stdout + out.stderr  # a stub that answers anything is none


def cli() -> str | None:
    """hal2-cli-plans when it has `overview`: `$HAL2_CLI_PLANS` when it names a file, else the one on PATH."""
    named = os.environ.get(CLI_ENV, "").strip()
    found = (str(Path(named).expanduser()) if Path(named).expanduser().is_file() else None) if named \
        else shutil.which(CLI_NAME)
    return found if found and cli_has_overview(found) else None


def write_by_cli(root: Path, folder: Path) -> bool:
    found = cli()
    if found is None:
        return False
    try:
        out = subprocess.run([found, "overview", folder.name, "--repo", str(root), "--write"],
                             capture_output=True, text=True, timeout=CLI_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0


def write_local(folder: Path) -> list[str]:
    """shape_overview's regeneration written; the paths it changed."""
    plan = folder / overview.PLAN_FILE
    changed = overview.regenerate(plan.read_text(), load(folder))
    for path, text in changed:
        (folder / path).write_text(text)
    return [path for path, _ in changed]


def write_overview(root: Path, folder: Path) -> str:
    """Regenerate the plan's overview and derived statuses: `hal2-cli-plans` when it can, else `shape.py`; returns
    which one wrote them."""
    if write_by_cli(root, folder):
        return CLI_NAME
    write_local(folder)
    return "shape.py"


def check_overview(folder: Path) -> list[str]:
    """The files whose derived parts are stale (overview-current, status-derived); empty when all is current."""
    return [path for path, _ in overview.regenerate((folder / overview.PLAN_FILE).read_text(), load(folder))]


def write_step(folder: Path, at: StepRef, **keys) -> Path:
    """Set front matter keys of one step file (`status` checked against the step's kind; None removes an optional
    key) and write it canonically; the caller regenerates the overview."""
    step = load(folder).step(at)
    if step is None:
        raise ShapeError(f"{folder.name} has no step {at}")
    doc = step.doc
    for key, value in keys.items():
        if key == "status":
            value = names.word(names.UAT_STEP if doc.uat else names.STEP, value)
        if not hasattr(doc, key) or key in ("rest", "body", "uat"):
            raise ShapeError(f"a {'UAT' if doc.uat else 'plan'} step has no key `{key}`")
        setattr(doc, key, value)
    path = folder / step.file
    path.write_text(doc.render())
    return path
