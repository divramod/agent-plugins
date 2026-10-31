"""The triage of a red step of a job that still runs (hal2 plan 0490 step 25, D25): the job's log is a 404 until the
job ends, so the verdict comes from the step's name, its duration and its runner (step_red.py's event), in the kinds
and the verdict shape of the finished run's triage (run_triage.py), so its dispatch, words and dedup take it as one
of theirs. Pure rule over data; run_triage_step_act.py reads and acts. The kinds, the first that holds:

- `runner`: a setup step of the runner (`Set up job`, checkout, tools, ...), or a job no runner name serves: nobody
- `unsure`: the same unit red in an earlier land run (a repeat, L131: never a car's, its cause needs the log), or a
  gate step red within QUICK seconds (no test ran: the log tells why): nothing ordered, the job's end decides
- `pipeline`: a car changed `.github/workflows/` or the gate: run_triage.pipeline_owner
- `car`: the one car whose files the unit names (a folder named like the unit's part, or its gate job's file), or,
  none named, the only car of a train without the yard's car (early_order.culprit's rule)
- `unplaced`: any other step (no `gate <job> [<part>]` step), or no car named: nothing ordered, the job's end decides

A placed verdict is rechecked from its evidence alone (run_triage_check.settle): a guess is never sent (D11). Its
key is the finished run's (`triage:<run>:<unit>`), its order's `triage:<run>:<bare job>` (run_triage_act.keys), so
the run's triage, reading the log at the end, orders nothing twice.

`target`: the train the fix rides, by when the step failed (D25): before the landing's merge into main (the merge
job's green, step_red.merged_at; hal2-git ends the landing `shipping` then) the CURRENT train, fixed in place (the
early order of today, no `--post`); after it the NEXT, still-open train (`--post`, rows 20-21's join and fix_wait).
"""

import re

import run_triage
import run_triage_check as check
import run_triage_read as read
import stack_red

SETUP = re.compile(r"^(?:Set up (?:job|runner)|Complete (?:job|runner)|Initialize containers|Stop containers|"
                   r"checkout|tools|Post .+|Run actions/.+)$", re.I)
GATE = re.compile(r"^gate (?P<job>\S+)(?: (?P<part>\S+))?$")
QUICK = 5  # seconds: a gate step red this soon ran no test
PLACED = ("car", "pipeline")


def task(step: str) -> str:
    """A step's task without its `[NN] ` number."""
    return read.NUMBER.sub("", step or "").strip()


def unit_of(ev: dict) -> dict:
    """The step's unit as run_triage_read names it ({unit, job, bare, part}); `part` None for no gate step."""
    m, bare = GATE.match(task(ev["step"])), stack_red.bare(ev["job"])
    unit = read.part_of({"name": ev["job"]}, {"name": task(ev["step"])}) if m else bare
    return {"unit": unit, "job": ev["job"], "bare": bare, "part": (m["part"] or m["job"]) if m else None}


def unit_files(part: str | None, cars: list[dict]) -> dict[str, list[str]]:
    """{car field: its files the unit names}: a path segment equal to the part, or the gate job's own file."""
    if not part:
        return {}
    gate = f"code/bash/scripts/gate/jobs/{part}.sh"
    out = {c["field"]: [f for f in c.get("files") or [] if f == gate or part in f.split("/")[:-1]] for c in cars}
    return {k: v for k, v in out.items() if v}


def repeat_of(unit: str, previous: list[dict]) -> str | None:
    """The earlier land run where the same unit was red (its kept signatures)."""
    return next((str(r.get("id")) for r in previous or [] if unit in (r.get("units") or {})), None)


def evidence(ev: dict, u: dict, ctx: dict) -> dict:
    runner = ev.get("runner") or ""
    line = (f"step {ev['step']} failed after {ev.get('secs') if ev.get('secs') is not None else '?'} s on "
            f"{runner or 'no runner'}, while the job runs (its log comes at the job's end)")
    return {"run": ev.get("url"), "id": ev.get("run"), "commit": ev.get("sha"), "runner": runner, "job": ev["job"],
            "unit": u["unit"], "steps": [ev["step"]], "lines": [line],
            "tests": [], "spec": None, "needs_red": [], "green_on": None, "repeat_of": None,
            "cars": [c["field"] for c in ctx.get("cars") or []], "unserved": not runner, "budget": False,
            "step": ev["step"], "secs": ev.get("secs"), "at": ev.get("at")}


def kind_of(ev: dict, u: dict, e: dict, ctx: dict) -> tuple[str, dict, str | None]:
    """(kind, owner record, what is missing) of the step red (see the module doc)."""
    if SETUP.match(task(ev["step"])) or not ev.get("runner"):
        return "runner", {}, None
    if rid := repeat_of(u["unit"], ctx.get("previous")):
        e["repeat_of"] = rid
        return "unsure", {}, f"the cause of a repeat of run {rid} (L131, never a car's): the job's log at its end"
    if not u["part"]:
        return "unplaced", {}, "a unit: the step is no `gate <job> [<part>]` step"
    if ev.get("secs") is not None and ev["secs"] < QUICK:
        return "unsure", {}, f"why the step ended after {ev['secs']} s, before a test ran: the job's log at its end"
    piped = run_triage.pipeline_owner(ctx, ev["job"])
    if piped["cars"]:
        e["pipeline"] = piped
        return "pipeline", piped, piped.get("missing")
    named, cars = unit_files(u["part"], ctx.get("cars") or []), ctx.get("cars") or []
    alone = cars[0]["field"] if len(cars) == 1 and not ctx.get("yard") else None  # early_order.culprit's only car
    car = next(iter(named)) if len(named) == 1 else alone if not named else None
    if not car:
        return "unplaced", {}, "the car whose files the unit names (none or several)"
    e["culprit"] = car
    e["lines"] += [f"the unit names {f}" for f in named.get(car, [])[:6]]
    return "car", {"field": car, "live": car in set(ctx.get("live") or ())}, None


def verdict(ev: dict, ctx: dict) -> dict:
    """The step red's verdict in run_triage's shape; `ctx`: cars, yard, live, previous, pipeline_field, gate_jobs."""
    u = unit_of(ev)
    e = evidence(ev, u, ctx)
    kind, owner, missing = kind_of(ev, u, e, ctx)
    e.update({"owner": owner, "culprit": e.get("culprit"), "pipeline": e.get("pipeline")})
    run = {"id": ev.get("run"), "url": ev.get("url"), "base": ctx.get("base")}
    v = {"key": f"triage:{ev.get('run')}:{u['unit']}", "kind": kind, "cause": kind if kind in PLACED else None,
         "owner": owner.get("field"), "live": bool(owner.get("live")), "evidence": e, "step": True,
         "reproduce": run_triage.reproduce(u, run, ctx.get("gate_jobs")), "reproduced": run_triage.REPRODUCED}
    if missing or (kind in PLACED and not v["owner"]):
        return check.unsure(v, missing)
    return check.settle(v) if kind in PLACED else v


def target(ev: dict, train: dict, standing: dict | None) -> str:
    """`current` (fixed in place before the merge) or `next` (rides the next, still-open train), see the module doc.
    A merge job green before the step's red, or green already when it is seen (the train is in the barn then: a
    fix cannot ride it), or a run whose train no longer lands: `next`."""
    if ev.get("merged_at") or (train or {}).get("state") not in (None, "landing"):
        return "next"
    own = bool(standing) and standing.get("train") == train.get("train") and standing.get("state") == "landing"
    return "current" if own else "next"
