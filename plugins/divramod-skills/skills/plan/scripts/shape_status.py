"""plan.py's step commands on the one plan shape (hal2 plan 0376, design §3 A6, A2, D19): `status <ref> <status>`,
`current`, `trailers [<ref>]` and `assign <NN> <who>` on a plan folder with `subplans/`.

A step is named by its ref `01.03`; a bare number is refused (the hint names the ref). The status is written into
the step file only (shape.write_step); then the overview and every derived status are regenerated, and plan.md's
`finished` is set exactly while the derived status is `uat` or `done` (the rule status-derived). In a sub-plan
servant's field (shape_lead) only that sub-plan's steps are written and the overview is left to the foreman.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import envelope
import folder as plan_folder
import shape
import shape_names as names
import shape_new
import trailers
import planhome
from shape_names import ShapeError, StepRef

PLAN_FILE = "plan.md"
WHO = re.compile(r"^(foreman|field \d{2})$")
LEAD_SKIP = "skipped: a servant never writes plan.md; the foreman regenerates it after the merge"


def ref(found: shape.Shape, text: str) -> StepRef:
    """`01.03` as a ref of a step the plan has; a bare `3` is refused with the ref to write."""
    text = text.strip()
    if "." not in text:
        hint = f"`{found.work()[0].id.number:02d}.{int(text):02d}`" if text.isdigit() and found.work() else \
            "`<sub-plan>.<step>`"
        raise ShapeError(f"step `{text}` is no ref: a plan of schema 2 names a step by its ref, e.g. {hint}")
    at = StepRef.parse(text)
    if found.step(at) is None:
        raise ShapeError(f"the plan has no step {at}")
    return at


def stamp_finished(folder: Path) -> str | None:
    """plan.md's `finished`: today's date once the derived status is `uat` or `done`, removed when it is `open`
    again (`abandoned` keeps what it has). The value written, or None."""
    path = folder / PLAN_FILE
    text = path.read_text()
    status, finished = envelope.get(text, "status"), envelope.get(text, "finished")
    if status in ("uat", "done") and not finished:
        finished = dt.date.today().isoformat()
        plan_folder.set_header(path, "finished", finished)
    elif status == "open" and finished:
        plan_folder.set_header(path, "finished", None)
        finished = None
    close_ledgers(folder, status)
    return None if finished is None else str(finished)


def close_ledgers(folder: Path, status: str) -> None:
    """The ledgers and the handoff are `open` exactly while the plan is (rule status-follows-plan): `closed` once
    it is `uat`, `done` or `abandoned`, `open` again when a step reopens it."""
    want = "open" if status == "open" else "closed"
    for name in plan_folder.SIBLINGS:
        other = folder / name
        if other.is_file() and plan_folder.is_record(other.read_text()):
            plan_folder.write_key(other, "status", want)


def set_status(root: Path, folder: Path, text: str, status: str, why: str | None, lead) -> dict:
    """`status <ref> <status> [--why]`: the step file's status (and `why`), then the regeneration."""
    found = shape.load(folder)
    if "." in text and StepRef.parse(text).subplan == names.UAT_NUMBER:
        raise ShapeError("a UAT step's status follows its verdict: `hal2-cli-plans uat set` queues it, the landing "
                         "writes it")
    at = ref(found, text)
    if lead is not None and at.subplan != lead.number:
        raise ShapeError(f"this servant runs sub-plan {lead} only: step {at} is the foreman's")
    keys = {"status": status.strip()}
    if why:
        keys["why"] = why
    path = shape.write_step(folder, at, **keys)
    out = {"ref": str(at), "status": keys["status"], "file": planhome.rel(path, root, posix=True)}
    if lead is not None:
        return {**out, "overview": LEAD_SKIP}
    out["overview"] = shape.write_overview(root, folder)
    out["finished"] = stamp_finished(folder)
    return out


def next_step(found: shape.Shape) -> tuple[shape.ShapeSubplan, shape.ShapeStep] | None:
    """The step that comes next: the first running or next one, else the first unfinished, in sub-plan order."""
    pairs = [(sub, step) for sub in found.work() for step in sub.steps]
    for wanted in (("next", "running"), ("open", "blocked")):
        hit = next(((sub, step) for sub, step in pairs if step.doc.status in wanted), None)
        if hit:
            return hit
    return None


def current(folder: Path, base: dict) -> dict:
    """`current` on schema 2: describe()'s keys with the derived status, done/total of the work steps (99-uat
    excluded), the next step's ref and sub-plan, and the open UAT checks."""
    found = shape.load(folder)
    counts = [sub.counts() for sub in found.work()]
    done, total = sum(c[0] for c in counts), sum(c[1] for c in counts)
    hit = next_step(found)
    at = str(StepRef(hit[0].id.number, hit[1].number)) if hit else None
    rows = {row["number"]: row for row in base.get("steps", [])}
    uat = found.uat()
    checks = [s.doc for s in uat.steps] if uat else []
    land = base["landing"]
    if land == "auto":
        land = "wait" if hit and not (rows.get(at) or {}).get("after_landing") else "ready"
    return {**base, "schema": 2, "status": found.derived(envelope.get((folder / PLAN_FILE).read_text(), "status")),
            "done": done, "total": total, "ref": at, "subplan": str(hit[0].id) if hit else None,
            "next": rows.get(at) if at else None, "land": land, "uat_checks": [c.check for c in checks],
            "uat_open": sum(1 for c in checks if not names.finished(c.status))}


def work_refs(found: shape.Shape) -> list[tuple[StepRef, str]]:
    return [(StepRef(sub.id.number, step.number), step.doc.status) for sub in found.work() for step in sub.steps]


def trailer_lines(root: Path, folder: Path, text: str | None) -> list[str]:
    """`trailers [<ref>]`: `Step: <ordinal among the work steps>/<work steps>` (the commit-msg rule's `<n>/<total>`;
    a ref `01.03/12` it refuses). Without a ref: the running or next step, else the last done one."""
    found = shape.load(folder)
    refs = work_refs(found)
    if not refs:
        raise trailers.TrailerError(f"plan {folder.name} has no work step")
    if text:
        at = ref(found, text)
    else:
        live = [r for r, s in refs if s in ("running", "next")]
        done = [r for r, s in refs if names.finished(s)]
        at = (live or done[-1:] or [refs[0][0]])[0]
    ordinal = [r for r, _ in refs].index(at) + 1
    return [f"Worktree: {trailers.worktree(root)}", f"Plan: {folder.name}", f"Step: {ordinal}/{len(refs)}"]


def assign(root: Path, folder: Path, number: str, who: list[str]) -> dict:
    """`assign <NN> <who>`: the work sub-plan's `who` (`foreman`, `field NN`; `-` clears it), then the overview."""
    text = " ".join(who).strip().lower()
    if text != "-" and not WHO.match(text):
        raise ShapeError(f"who `{text}` is none of `foreman`, `field NN` (a servant's field 30-99), `-`")
    sub = shape_new.find_subplan(shape.load(folder).work(), number)
    doc = sub.copy_doc()
    doc.who = None if text == "-" else text
    (folder / sub.file).write_text(doc.render())
    return {"plan": folder.name, "subplan": str(sub.id), "who": doc.who,
            "overview": shape.write_overview(root, folder)}
