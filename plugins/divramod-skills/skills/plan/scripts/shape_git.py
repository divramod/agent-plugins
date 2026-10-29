"""`plan.py subplan start <NN>` and `subplan finish <NN>` (hal2 plan 0376, design §5 A9; record
side-branches-carry-the-slot-number): the foreman's hands build a sub-plan on the side branch `<field>-<NN>`, so the
field's branch `<field>` holds only finished sub-plans and a mid-plan landing (`/mtm milestone`, only on the user's
word) delivers exactly the finished deliverables.

`start` switches to `<field>-<NN>`, created from `<field>` when missing; `finish` checks the sub-plan's done-when
passed (every step done or dropped), switches back to `<field>` and merges the side branch `--no-ff`. Both refuse a
dirty tree (tracked changes); the field is the checkout's folder name (`07`).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import planread
import shape
import shape_names as names
import shape_new
from shape_names import ShapeError


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def must(root: Path, *args: str) -> str:
    out = git(root, *args)
    if out.returncode != 0:
        raise ShapeError(f"git {' '.join(args)}: {(out.stderr or out.stdout).strip()}")
    return out.stdout.strip()


def clean_tree(root: Path, what: str) -> None:
    if must(root, "status", "--porcelain", "--untracked-files=no"):
        raise ShapeError(f"the worktree has uncommitted changes: commit them before `subplan {what}`")


def branches(root: Path, folder: Path, number: str):
    """The sub-plan, the field's branch and the sub-plan's side branch."""
    sub = shape_new.find_subplan(shape.load(folder).work(), number)
    field = root.resolve().name
    return sub, field, f"{field}-{sub.id.number:02d}"


def exists(root: Path, branch: str) -> bool:
    return git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0


def start(root: Path, folder: Path, number: str) -> dict:
    sub, field, side = branches(root, folder, number)
    here = must(root, "branch", "--show-current")
    out = {"subplan": str(sub.id), "branch": side, "from": field}
    if here == side:
        return {**out, "switched": False}
    if here != field:
        raise ShapeError(f"`subplan start` runs on the field's branch `{field}`, not on `{here or 'a detached HEAD'}`")
    clean_tree(root, "start")
    if exists(root, side):
        must(root, "switch", side)
        return {**out, "switched": True, "created": False}
    must(root, "switch", "-c", side, field)
    return {**out, "switched": True, "created": True}


def message(root: Path, folder: Path, field: str, sub) -> str:
    """The merge's message: the subject and the origin trailers; where the farm's commits are neutral (hal2 plan 0409
    D15) the subject alone, naming no plan or field."""
    if planread.neutral(root):
        return f"chore(plans): merge sub-plan {sub.id}\n"
    found = shape.load(folder)
    steps = [s for w in found.work() for s in w.steps]
    done = sum(1 for s in steps if names.finished(s.doc.status))
    return (f"chore(plans): merge sub-plan {sub.id} of plan {folder.name}\n\nWorktree: {field}\nPlan: {folder.name}\n"
            f"Step: {done}/{len(steps)}\n")


def finish(root: Path, folder: Path, number: str) -> dict:
    sub, field, side = branches(root, folder, number)
    if not exists(root, side):
        raise ShapeError(f"sub-plan {sub.id} has no side branch `{side}`: `plan.py subplan start {number}` makes it")
    clean_tree(root, "finish")
    if must(root, "branch", "--show-current") != side:
        must(root, "switch", side)
    left = [f"{s.number:02d}" for s in shape_new.find_subplan(shape.load(folder).work(), number).steps
            if not names.finished(s.doc.status)]
    if left:
        raise ShapeError(f"sub-plan {sub.id} is not done: its steps {', '.join(left)} are open (its done-when "
                         "passes only with every step done or dropped)")
    text = message(root, folder, field, sub)
    must(root, "switch", field)
    merged = git(root, "merge", "--no-ff", side, "-m", text)
    if merged.returncode != 0:
        git(root, "merge", "--abort")
        must(root, "switch", side)
        raise ShapeError(f"merging `{side}` into `{field}` failed, aborted: {(merged.stderr or merged.stdout).strip()}")
    return {"subplan": str(sub.id), "merged": side, "into": field, "head": must(root, "rev-parse", "--short", "HEAD")}
