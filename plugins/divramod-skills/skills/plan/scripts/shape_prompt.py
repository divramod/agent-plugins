"""`plan.py prompt <ref>` on the one plan shape (hal2 plan 0376, design A2; record subagent-names-plan-row): the Agent
call that runs one step in one hand, built from the step file alone: its task, done-when and size, the sub-plan's
goal and deliverable, the links the step names. The description is `Plan <NNNN> row <ref>: <title>`.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import envelope
import prompt as step_prompt
import shape
import shape_names as names
import sizing
from shape_names import ShapeError

PLACEHOLDER = re.compile(r"^<what (the step does|to change)\b.*>$", re.S)


def task_of(body: str) -> str:
    return envelope.section(body, "Task").strip()


def refuse(rel: str, at, doc, task: str, effort: str) -> None:
    """Why the step cannot run in a hand yet: no written task, or its sizing fails plan-steps-sized."""
    if not task or PLACEHOLDER.match(task):
        raise ShapeError(f"{rel} has no written `## Task`: write the step's task first")
    why = [w for k in sizing.SIZED if (w := sizing.cell_problem(k, getattr(doc, k) or "", doc.window or ""))]
    if why:
        raise ShapeError(f"step {at}: {'; '.join(why)}: fix the step file's front matter ({sizing.RULE})")
    if effort and effort not in sizing.EFFORTS:
        raise ShapeError(f"--effort '{effort}' is none of {', '.join(sizing.EFFORTS)}")


def reads(root: Path, folder: Path, sub, step, links: list[str]) -> list[str]:
    rel = lambda p: p.relative_to(root).as_posix()  # noqa: E731
    out = [f"your step file {rel(folder / step.file)}", f"its sub-plan {rel(folder / sub.file)}",
           f"the plan {rel(folder / 'plan.md')} (its Goal, Brief and Context)"]
    if (folder / "decisions.md").is_file():
        out.append(f"the plan's decisions {rel(folder / 'decisions.md')} (decided: never re-decide them)")
    base = (folder / step.file).parent
    for link in links:
        target = Path(os.path.normpath(base / link))
        out.append(rel(target) if target.is_relative_to(root) else link)
    return out


def text(root: Path, folder: Path, sub, step, at, part: int | None) -> str:
    doc, number = step.doc, folder.name[:4]
    others = [f"{names.StepRef(sub.id.number, s.number)} {step_prompt.short_title(s.doc.title)}"
              for s in sub.steps if s is not step and not names.finished(s.doc.status)]
    retry = (f" This is part {part} of the step: an earlier hand's work is in the worktree and in the step file's "
             "Approach and Notes; continue from it.") if part else ""
    rules = next((name for name in ("AGENTS.md", "CLAUDE.md") if (root / name).is_file()), "")
    goal = envelope.section(sub.doc.body, "Goal").strip()
    done_when = envelope.section(doc.body, "Done when").strip() or doc.description
    return "\n\n".join([
        f"You are the hand for step {at} of plan {number} in the {step_prompt.repo_name(root)} repository. Work "
        f"only in the git worktree {root}.{retry}",
        f"Step {at}: {doc.title}\n\nTask:\n{task_of(doc.body)}\n\nDone when: {done_when}\n\n"
        f"Size: {doc.size} of {doc.window}",
        f"Sub-plan {sub.id}: {sub.doc.title}. Goal: {goal or '-'} Deliverable: {sub.doc.description}",
        "Read first: " + "; ".join(reads(root, folder, sub, step, envelope.links(doc.body)))
        + (f". The repo's rules: {rules}." if rules else "."),
        "Rules: edit files, but never commit, push, land or change git state, never set a status and never edit "
        "plan.md, a subplan.md or another step's file (the coordinator reviews, marks and commits). First write "
        "your step file's `## Approach`; at the end its `## Notes` (what changed, the checks and results, what you "
        f"decided). Stay inside your step (the other open steps of the sub-plan: {'; '.join(others) or 'none'}). "
        "Run the step's done-when and the tests of what you changed until green. Never print the whole environment "
        "(`env`, `printenv`, `set`, `export -p`): it holds secrets.",
        "Final reply, at most 15 lines: the files changed, the done-when's result, follow-ups for later steps.",
    ])


def call(root: Path, folder: Path, at, part: int | None = None, model: str = "", effort: str = "") -> dict:
    """The Agent call for step `at` (a StepRef); `model`/`effort` override the step's (an escalation)."""
    found = shape.load(folder)
    sub, step = found.subplan(at.subplan), found.step(at)
    if step is None or sub is None:
        raise ShapeError(f"the plan has no step {at}")
    if sub.id.is_uat():
        raise ShapeError("a 99-uat step is the user's check after the landing, never a hand's")
    if part is not None and part < 2:
        raise ShapeError("--part counts the retries from 2 (part 1 is the first run)")
    refuse(step.file, at, step.doc, task_of(step.doc.body), effort)
    out = {"description": f"Plan {folder.name[:4]} row {at}{f' part {part}' if part else ''}: "
                          f"{step_prompt.short_title(step.doc.title)}"}
    try:
        out["model"] = step_prompt.alias(model or step.doc.model or "")
    except step_prompt.PromptError as error:
        raise ShapeError(str(error)) from error
    out["effort"] = effort or sizing.clean(step.doc.effort or "")
    out["run_in_background"] = True
    out["prompt"] = text(root, folder, sub, step, at, part)
    return out
