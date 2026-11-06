"""`plan.py finish <ref> [--next <ref>]`: a plan's step boundary in one call and one JSON (hal2 plan 0485 step
03.01; research 0118 #4). It does in one process what the coordinator did in about eight calls of plan.py and
context.py after a step's check passed:

  status <ref> done        the step done: schema 1 the table cell (its masterplan row ticked or taken back),
                           schema 2 the step file, the overview, `finished` and the masterplan row (the rule
                           masterplan-rows); --why: a schema 2 step's `why`
  status <next> next       with --next: schema 1 also writes the step's file steps/<n>.md when missing
  scope, trailers <ref>    the commit's subject scope and its origin trailers (a neutral farm: "" and [], the next
                           commit linked to the step in the plan store, as `trailers` does)
  run --sync               the coordinator's live model, effort and window into `run` (a sub-plan servant: skipped,
                           `run` is the foreman's)
  context.py               the context check, from the same one parse of the transcript as the sync
  current                  the plan's done, total, next step and `land`

The JSON: {plan, schema, step, next, overview, finished, tick, tick_skipped, scope, trailers, run, context, stop,
autoclear, done, total, land, landing, upcoming, problems}; `stop` and `autoclear` are the context check's (the
coordinator hands off when `stop` is true). Every ref is checked before anything is written. In the store home it
runs on the view of the plan like `status` (storerun.py), and the store's sync trigger fires after it.

Like masterplan_keep.py it imports no plan.py (that runs as `__main__`): plan.py passes it its functions (`Ops`).
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import context
import masterplan
import masterplan_keep
import neutral_commit
import planhome
import session
import shape
import shape_lead
import shape_status
import trailers
from shape_names import ShapeError

RUN_SKIPPED = "skipped: a servant never writes plan.md; `run` is the foreman's"


@dataclass
class Ops:
    """plan.py's own functions finish needs: set_status(path, n, status) -> tick, scaffold_step(path, n) -> file,
    describe(path) -> dict, read_steps(text) -> rows, run_values(path, args, live) -> dict, stamp_finished(path)."""
    set_status: Callable
    scaffold_step: Callable
    describe: Callable
    read_steps: Callable
    run_values: Callable
    stamp_finished: Callable


def add_parser(sub) -> None:
    p = sub.add_parser("finish", help="a step boundary in one call: the step done, the next one next, scope, "
                                      "trailers, run --sync and the context check as one JSON")
    p.add_argument("step", help="the step that passed its check (schema 2: its ref `01.03`)")
    p.add_argument("--next", dest="next_step", default="", metavar="REF", help="the step to mark next")
    p.add_argument("--plan")
    p.add_argument("--why", help="a schema 2 step's `why`: a done note")
    p.add_argument("--threshold", type=float, help="the context check's percent (default: hal2's autoclear)")
    p.add_argument("--transcript", default="", help="the session's transcript (default: $CLAUDE_CODE_SESSION_ID's)")


def run(root: Path, path: Path, args, ops: Ops) -> dict:
    """The boundary on the plan file `path`; the JSON (see the module's doc)."""
    step, after = args.step.strip(), (args.next_step or "").strip()
    if after and after == step:
        raise ShapeError(f"--next names the finished step {step} again: name the step that comes next")
    if path.name == shape_status.PLAN_FILE and shape.is_shape(path.parent):
        out, lead = schema_two(root, path, step, after, args.why, ops), shape_lead.lead(root, path.parent.name)
    else:
        out, lead = schema_one(root, path, step, after, ops), None
    out.update(boundary(root, path, step, lead is not None, args, ops))
    return out


def schema_one(root: Path, path: Path, step: str, after: str, ops: Ops) -> dict:
    numbers = [s["number"] for s in ops.read_steps(path.read_text())]
    for ref in filter(None, (step, after)):
        if ref not in numbers:
            raise trailers.TrailerError(f"step {ref!r} is no row of plan {masterplan.slug_of(path)}: "
                                        f"{', '.join(numbers) or 'no steps'}")
    ticks = [ops.set_status(path, step, "done")]
    out = {"schema": 1, "step": {"ref": step, "status": "done"}, "next": None}
    if after:
        ticks.append(ops.set_status(path, after, "next"))
        written = ops.scaffold_step(path, after)
        out["next"] = {"ref": after, "status": "next",
                       "step_file": planhome.rel(written, root, posix=True) if written else None}
    out.update(masterplan_keep.report(last_tick(ticks)))
    scope = trailers.scope(masterplan.slug_of(path), masterplan.parent_of(path.read_text()), numbers, step)
    lines = trailers.lines(root, masterplan.slug_of(path), numbers, step)
    return {**out, **commit_fields(root, scope, lines)}


def schema_two(root: Path, path: Path, step: str, after: str, why: str | None, ops: Ops) -> dict:
    folder = path.parent
    found = shape.load(folder)
    for ref in filter(None, (step, after)):
        shape_status.ref(found, ref)
    lead = shape_lead.lead(root, folder.name)
    done = shape_status.set_status(root, folder, step, "done", why, lead)
    out = {"schema": 2, "step": {k: done[k] for k in ("ref", "status", "file")}, "next": None,
           "overview": done["overview"], "finished": done.get("finished")}
    if after:
        nexted = shape_status.set_status(root, folder, after, "next", None, lead)
        out["next"] = {k: nexted[k] for k in ("ref", "status", "file")}
        out["overview"], out["finished"] = nexted["overview"], nexted.get("finished")
    if lead is None:
        out.update(masterplan_keep.report(tick_two(path, ops)))
    lines = shape_status.trailer_lines(root, folder, step)
    numbers = [str(r) for r, _ in shape_status.work_refs(shape.load(folder))]
    scope = trailers.scope(folder.name, masterplan.parent_of(path.read_text()), numbers, step)
    return {**out, **commit_fields(root, scope, lines)}


def tick_two(path: Path, ops: Ops) -> dict | None:
    """A schema 2 plan of a masterplan holds its row to the plan's derived `status` (masterplan_keep.tick), and the
    masterplan is stamped after a written tick, as plan.py's stamp_finished does for a schema 1 plan."""
    ticked = masterplan_keep.tick(path)
    if ticked and ticked.get("row"):
        master = path.parent.parent / ticked["masterplan"] / shape_status.PLAN_FILE
        ops.stamp_finished(master)
        ticked["masterplan_finished"] = bool(ops.describe(master)["finished"])
    return ticked


def last_tick(ticks: list[dict | None]) -> dict | None:
    """The tick that holds now: the last one that wrote or skipped a row (`done` then `next` may tick and take back)."""
    return next((t for t in reversed(ticks) if t), None)


def commit_fields(root: Path, scope: str, lines: list[str]) -> dict:
    """The step commit's `scope` and `trailers`; a neutral farm's are empty and the next commit is linked instead."""
    neutral = neutral_commit.trailers(root, lines)
    return {"scope": "" if neutral else scope, "trailers": [] if neutral else lines, "neutral": neutral}


def boundary(root: Path, path: Path, step: str, servant: bool, args, ops: Ops) -> dict:
    """`run --sync`, the context check and the plan's state, from one parse of the session's transcript."""
    home = Path(os.environ.get("HOME", str(Path.home())))
    reading = argparse.Namespace(threshold=args.threshold, window=None, session=None,
                                 transcript=args.transcript or None)
    scanned = context.scan_session(reading, home)
    live = session.values(scanned[0], home)
    if servant:
        run_out = {"run": masterplan.key(path.read_text(), "run"), "skipped": RUN_SKIPPED}
        run_now = ""
    else:
        sync = argparse.Namespace(sync=True, check=False, model=None, effort=None, window=None)
        synced = ops.run_values(path, sync, live)
        run_out = {k: synced[k] for k in ("run", "before", "drift")}
        run_now = synced["run"]
    checked = context.measure(reading, home, scanned, live, (masterplan.slug_of(path), run_now))
    keep = ("known", "used", "window", "percent", "threshold", "stop", "source", "autoclear", "autoclear_reason",
            "drift")
    return {"plan": masterplan.slug_of(path), "run": run_out, "context": {k: checked[k] for k in keep},
            "stop": checked["stop"], "autoclear": checked["autoclear"], **state(root, path, ops)}


def state(root: Path, path: Path, ops: Ops) -> dict:
    """What `current` would say after the boundary: done/total, the step that comes next, `land`."""
    described = ops.describe(path)
    if path.name == shape_status.PLAN_FILE and shape.is_shape(path.parent):
        described = shape_status.current(path.parent, described)
    upcoming = described.get("next")
    if upcoming:
        upcoming = {k: upcoming.get(k) for k in ("number", "step", "done_when", "model", "effort", "window", "size")}
    return {"done": described["done"], "total": described["total"], "upcoming": upcoming,
            "landing": described["landing"], "land": described["land"], "problems": described["problems"],
            "plan_status": described.get("status") or masterplan.key(path.read_text(), "status")}
