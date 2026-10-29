"""Writing the one plan shape (hal2 plan 0376, design §1, A2, A5, A12): the sub-plans and steps of a new plan
(`plan.py new`), `plan.py subplan new <title> [--wave n]` and `plan.py step add <subplan> <title> [--wave n]
[sizing]`. Numbers go on, never renumbered (A2); a new sub-plan or step gets the `wave` one above the highest of its
level unless `--wave` joins one (A5); every write regenerates the overview (shape.write_overview).
"""
from __future__ import annotations

import re
from pathlib import Path

import envelope
import folder as plan_folder
import names
import shape
import shape_names as sn
import planhome
from shape_docs import PlanStep, Subplan
from shape_names import ShapeError

PLAN_FILE = "plan.md"
PLACEHOLDER_GOAL = "<one or two sentences>"
UAT_DELIVERABLE = "The user's checks on the default branch after the landing."
UAT_BODY = """
# Sub-plan 99: uat

## Goal

The user confirms by hand on the default branch what the plan delivered.

## Before you start

The plan is brought in and what it changed is installed from the default branch.

## Done when

Every check has a verdict.
"""
UAT_WRITER = ("Write the UATs and the changelog fragment",
              "`plan.py current` shows the 99-uat checks; `hal2-cli-changelog check` passes",
              "The user acceptance tests as 99-uat steps, only the checks a human must do after the landing,\n"
              "and the changelog fragment `changelog.md` beside plan.md (`plan.py changelog`).")


def slug_of(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].rstrip("-")
    if not slug:
        raise ShapeError("a title needs at least one letter or digit")
    return slug


def feature(title: str) -> str | None:
    """The feature the title names first (`plugin-plan 9` -> `plugin-plan`): 99-uat's shotfile, as uat.md's was."""
    word = re.sub(r"[^a-z0-9]+", "-", (title.split() or [""])[0].lower()).strip("-")
    return word or None


def subplan_body(number: int, title: str, goal: str) -> str:
    return (f"\n# Sub-plan {number:02d}: {title}\n\n## Goal\n\n{goal or PLACEHOLDER_GOAL}\n\n## Done when\n\n"
            "<a check anyone can run that proves the deliverable>\n")


def step_body(number: int, title: str, task: str) -> str:
    return f"\n# Step {number:02d}: {title}\n\n## Task\n\n{task or '<what the step does>'}\n"


def plan_id(folder: Path) -> int:
    value = envelope.get((folder / PLAN_FILE).read_text(), "id")
    return int(value) if value is not None and str(value).isdigit() else int(folder.name[:4])


def run_words(folder: Path) -> list[str]:
    """The plan's `run` (the coordinator's model, effort, window, its model as the alias `opus`): a new step's
    defaults."""
    run = envelope.get((folder / PLAN_FILE).read_text(), "run") or ""
    words = (str(run).split() + ["", "", ""])[:3]
    family = re.match(r"^claude-(haiku|sonnet|opus|fable)\b", words[0])
    return [family.group(1) if family else words[0], *words[1:]]


def write_subplan(folder: Path, number: int, slug: str, doc: Subplan) -> Path:
    path = folder / shape.SUBPLANS / f"{number:02d}-{slug}" / "subplan.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc.render())
    return path


def write_step(sub_dir: Path, number: int, doc: PlanStep, wide: bool = False) -> Path:
    path = sub_dir / "steps" / sn.step_file(number, wide)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc.render())
    return path


def scaffold(root: Path, folder: Path, title: str, goal: str, research: bool) -> str:
    """A new plan's sub-plans: `01-<slug>` with its first step (and, for an implementation plan, the step that
    writes the UATs and the changelog fragment) and an empty `99-uat` (A12); then the overview. Returns which tool
    wrote the overview."""
    plan, slug = plan_id(folder), slug_of(title)
    model, effort, window = run_words(folder)
    first = Subplan(title=title, description=plan_folder.describe(goal, title), status="open", plan=plan, wave=1,
                    body=subplan_body(1, title, goal))
    sub_dir = write_subplan(folder, 1, slug, first).parent
    steps = [("<step>", "<a check anyone can run>", "", "opus", "medium", "1m", "150k")]
    if not research:
        steps.append((*UAT_WRITER, "sonnet", "medium", "1m", "100k"))
    for n, (step_title, done_when, task, *sizing) in enumerate(steps, 1):
        write_step(sub_dir, n, PlanStep(title=step_title, description=done_when, status="open", plan=plan,
                                        subplan=1, wave=n, model=sizing[0] or model, effort=sizing[1] or effort,
                                        window=sizing[2] or window, size=sizing[3], body=step_body(n, step_title,
                                                                                                   task)))
    uat = Subplan(title="uat", description=UAT_DELIVERABLE, status="done", plan=plan,
                  shotfile=feature(title), body=UAT_BODY)
    write_subplan(folder, sn.UAT_NUMBER, "uat", uat)
    return shape.write_overview(root, folder)


def add_subplan(root: Path, folder: Path, title: str, goal: str = "", wave: int | None = None) -> dict:
    """`subplan new`: the next work sub-plan `NN-<slug>` (01-98), its wave one above the highest unless given."""
    names.refuse(title)
    work = shape.load(folder).work()
    number = max((s.id.number for s in work), default=0) + 1
    if number >= sn.UAT_NUMBER:
        raise ShapeError(f"{folder.name} has no sub-plan number left below {sn.UAT_NUMBER}")
    if wave is None:
        wave = max((s.doc.wave or 0 for s in work), default=0) + 1
    if wave < 1:
        raise ShapeError("`--wave` starts at 1")
    doc = Subplan(title=title, description=plan_folder.describe(goal, title), status="open", plan=plan_id(folder),
                  wave=wave, body=subplan_body(number, title, goal))
    path = write_subplan(folder, number, slug_of(title), doc)
    return {"added": "subplan", "plan": folder.name, "subplan": path.parent.name, "wave": wave,
            "file": planhome.rel(path, root, posix=True), "overview": shape.write_overview(root, folder)}


def find_subplan(work: list, ref: str):
    """A work sub-plan by number (`2`, `02`) or folder name (`02-readers`)."""
    ref = ref.strip().rstrip("/").split("/")[-1]
    for sub in work:
        if ref == str(sub.id) or (ref.isdigit() and int(ref) == sub.id.number):
            return sub
    raise ShapeError(f"no work sub-plan `{ref}` (99-uat's steps are UAT checks: `plan.py uat add`)")


def add_step(root: Path, folder: Path, subplan: str, title: str, wave: int | None = None, done_when: str = "",
             sizing: dict | None = None, task: str = "") -> dict:
    """`step add`: the next step of a work sub-plan, `open`, its wave one above the highest unless given; model,
    effort and window default to the plan's `run`, size stays empty unless given (plan-steps-sized names it)."""
    sub = find_subplan(shape.load(folder).work(), subplan)
    number = max((s.number for s in sub.steps), default=0) + 1
    if wave is None:
        wave = max((s.doc.wave or 0 for s in sub.steps), default=0) + 1
    if wave < 1:
        raise ShapeError("`--wave` starts at 1")
    run, sizing = run_words(folder), sizing or {}
    pick = lambda key, i: sizing.get(key) or run[i] or None
    doc = PlanStep(title=title, description=done_when or "<a check anyone can run>", status="open",
                   plan=plan_id(folder), subplan=sub.id.number, wave=wave, model=pick("model", 0),
                   effort=pick("effort", 1), window=pick("window", 2), size=sizing.get("size") or None,
                   body=step_body(number, title, task))
    wide = number > 99 or any(len(Path(s.file).stem) > len("step-NN") for s in sub.steps)
    path = write_step(folder / Path(sub.file).parent, number, doc, wide)
    return {"added": "step", "plan": folder.name, "ref": str(sn.StepRef(sub.id.number, number)), "wave": wave,
            "file": planhome.rel(path, root, posix=True), "overview": shape.write_overview(root, folder)}
