#!/usr/bin/env python3
"""The triage of a finished land run (hal2 plan 0490 step 1; D3, D4, D11, D12, D13; learnings L131, L132): one
verdict per red unit of the run, as code, so the model is woken only for what the code cannot place. Pure rule over
data: run_triage_read.py parses, run_triage_gather.py reads gh and git, run_triage_check.py rechecks.

A unit is a failed `gate <job> <part>` step (`stack-test/hub-e2e`), else a red job; a unit failing in specs gives a
verdict per spec file. The kinds, the first that holds:

- `needs-red`: a job it needs (the workflow's `needs`) is red: nobody (hub-deploy after a red stack-test)
- `runner`: its log shows a transient fault (transient.TRANSIENT): nobody, trains.settle retries
- `runner` also: a job no runner served (no step, L64)
- `flake`: the same unit is green in another run of the same content (the head's tree), or it failed only on a
  latency budget or a test's time limit (L13, `budget`): nobody, no rerun (D12); a budget flake that repeats
  (`repeat_of`) is the flaky brief's (run_triage_act.py)
- `repeat`: the same unit and failing test (or the same build-phase timeout) red in a previous land run (L131):
  never a car's; its `cause` (file or pipeline) names the owner, else `unsure`
- `file`: a failing spec: the field of its newest commit (`Worktree:` trailer, live), else the field running the
  commit's plan, else the car of that plan or the one car whose diff touched it, else no field (an unowned red: a board note, D5)
- `pipeline`: a build-phase timeout (exit 124, D13), or a workflow or gate change in the range: the one car that
  changed the pipeline, else the pipeline's field (`pipeline_field`, L132: the user's pipeline-speed field)
- `car`: early_order.culprit names one car; else `unplaced` (the one wake per run)
- `unsure`: the owner is unclear or the evidence thin, with `missing`; never a field (D11)

Every verdict carries its evidence (lines, commit, runner), a dedup `key`, `reproduce` (the gate job, else the one CI
job) and `reproduced` (D12: never by the tollman). `triage` also carries the dedup data for step 2.
"""

import early_order
import proof_lanes
import run_triage_check as check
import run_triage_read as read

REPRODUCED = ("not reproduced: the tollman never runs a gate job beside a train (speed rule); "
              "the receiving field reproduces first")
PIPELINE = (".github/workflows/", "code/bash/scripts/gate/")
QUIET = ("needs-red", "runner", "flake")  # nobody is sent for these


def resolve(spec: dict, paths: list[str]) -> str | None:
    """The repository path of a failing spec (its longer log form first), when exactly one path ends with it."""
    for name in filter(None, (spec.get("path"), spec.get("file"))):
        hits = [p for p in paths if p == name or p.endswith("/" + name)]
        if len(hits) == 1:
            return hits[0]
    return None


def running(plans: dict, plan: str) -> str | None:
    """The field whose current plan is `plan` (matched by its number), or None."""
    number = (plan or "").split("-", 1)[0]
    hits = [f for f, p in (plans or {}).items() if number and (p or "").split("-", 1)[0] == number]
    return hits[0] if len(hits) == 1 else None


def owner_of(path: str, ctx: dict) -> dict:
    """{field, live, from}: who owns a failing file (see the module doc); field None: an unowned red."""
    commit, live = (ctx.get("owners") or {}).get(path), set(ctx.get("live") or ())
    if not commit:
        return {"field": None, "live": False, "from": None, "missing": f"the newest commit of {path}"}
    w = (commit.get("worktree") or "").strip()
    touched = [c for c in ctx.get("cars") or [] if path in (c.get("files") or [])]
    mine = [c["field"] for c in touched if running({c["field"]: c.get("plan")}, commit.get("plan"))]
    cars = mine or [c["field"] for c in touched]
    for field, how in ((w if w in live else None, "worktree"), (running(ctx.get("plans"), commit.get("plan")), "plan"),
                       (cars[0] if len(cars) == 1 else None, "car"), (w or None, "worktree")):
        if field:
            return {"field": field, "live": field in live, "from": {**commit, "by": how}}
    return {"field": None, "live": False, "from": commit}


def pipeline_owner(ctx: dict, job: str | None = None) -> dict:
    """{field, live, cars, movers}: the one car that changed the pipeline, else, of several, the one that moved the
    red job's lane (proof_lanes.mover, L83, L87), else the pipeline's field; else `missing`."""
    cars = sorted({c["field"] for c in ctx.get("cars") or [] if any(f.startswith(PIPELINE) for f in c.get("files") or [])})
    movers = sorted(set(proof_lanes.mover(job, ctx.get("moved") or {})) & set(cars)) if job and len(cars) > 1 else []
    field = cars[0] if len(cars) == 1 else movers[0] if len(movers) == 1 else (
        ctx.get("pipeline_field") if not cars else None)
    out = {"field": field, "live": field in set(ctx.get("live") or ()), "cars": cars, "movers": movers,
           "configured": ctx.get("pipeline_field")}
    if not field:
        out["missing"] = (f"one field: cars {', '.join(cars)} all changed the pipeline" if cars else
                          "the field owning the pipeline (no car changed .github/workflows/ or the gate)")
    return out


def repeat_of(unit: str, spec: dict | None, facts: dict, previous: list[dict]) -> str | None:
    """The previous land run where the same unit was red with the same failing test, or the same build-phase
    timeout (or, without either, the same first error line)."""
    tests = set(spec["tests"]) if spec else set(facts["tests"])
    for run in previous or []:
        was = (run.get("units") or {}).get(unit)
        if was and ((tests & set(was.get("tests") or [])) or (not tests and facts["timeout"] and was.get("timeout"))
                    or (not tests and not facts["timeout"] and facts["errors"][:1]
                        and facts["errors"][:1] == (was.get("lines") or [])[:1])):
            return str(run.get("id"))
    return None


def flake_of(unit: dict, others: list[dict]) -> str | None:
    """Another run of the same content where the unit (or its whole job) was green."""
    return next((str(o.get("id")) for o in others or [] if unit["unit"] in o.get("green", ())
                 or unit["bare"] in o.get("green", ())), None)


def cause(unit: dict, spec: dict | None, f: dict, ctx: dict, repeat: str | None) -> tuple[str, dict]:
    """(file | pipeline | car | unplaced, the owner record) of one verdict."""
    if spec:
        path = resolve(spec, ctx.get("paths") or [])
        if not path:
            return "file", {"field": None, "live": False, "file": None,
                            "missing": f"the spec's file in the repository ({spec['file']})"}
        return "file", {**owner_of(path, ctx), "file": path}
    piped = pipeline_owner(ctx, unit["job"])
    if f["timeout"] or piped["cars"]:
        return "pipeline", piped
    tail = "\n".join(unit["lines"])
    car = None if repeat else early_order.culprit(
        {"yard": ctx.get("yard") or []},
        {"kind": "car", "evidence": {"cars": ctx.get("cars") or [], "tail": tail, "tests": f["tests"]}})
    return ("car", {"field": car, "live": car in set(ctx.get("live") or ())}) if car else ("unplaced", {"field": None})


def reproduce(unit: dict, run: dict, gate_jobs) -> str:
    """The command the receiving field runs first: the gate job of the unit, else the one CI job."""
    part = unit["unit"].split("/", 1)[-1]
    if part in set(gate_jobs or ()):
        return f"code/bash/scripts/gate/main.sh {part} --branch {run.get('base') or 'origin/main'}"
    return f"code/bash/scripts/ci-check/main.sh {unit['bare']}"


def verdict(run: dict, unit: dict, spec: dict | None, f: dict, ctx: dict) -> dict:
    """One verdict, before the recheck."""
    needs = read.needs_red(unit["job"], ctx.get("graph") or {}, ctx.get("red") or [])
    runner = f["transient"] or ("no runner served the job" if unit.get("unserved") else "")  # L64
    flake = None if needs or runner else flake_of(unit, ctx.get("others"))
    repeat = None if needs or runner or flake else repeat_of(unit["unit"], spec, f, ctx.get("previous"))
    e = {"run": run.get("url"), "id": run.get("id"), "commit": run.get("sha"), "runner": unit.get("runner") or f["runner"],
         "job": unit["job"], "unit": unit["unit"], "steps": unit["steps"],
         "lines": read.evidence_lines(f["errors"], spec, f["specs"]), "tests": spec["tests"] if spec else f["tests"],
         "spec": spec["file"] if spec else None, "needs_red": needs, "green_on": flake, "repeat_of": repeat,
         "cars": [c["field"] for c in ctx.get("cars") or []], "unserved": bool(unit.get("unserved")),
         "budget": f["budget"]}
    quiet = "needs-red" if needs else "runner" if runner else "flake" if flake or f["budget"] else None
    kind, why, owner = quiet, None, {}
    if not kind:
        why, owner = cause(unit, spec, f, ctx, repeat)
        e.update({"file": owner.get("file"), "owner": owner, "culprit": owner["field"] if why == "car" else None,
                  "pipeline": pipeline_owner(ctx, unit["job"]) if why == "pipeline" else None})
        kind = "repeat" if repeat else why
    key = f"triage:{run.get('id')}:{unit['unit']}" + (f":{spec['file']}" if spec else "")
    v = {"key": key, "kind": kind, "cause": why, "owner": owner.get("field"), "live": bool(owner.get("live")),
         "evidence": e, "reproduce": reproduce(unit, run, ctx.get("gate_jobs")), "reproduced": REPRODUCED}
    if kind == "repeat" and not owner.get("field") and why != "file":
        return check.unsure(v, owner.get("missing") or f"the owner of this repeat (red before in run {repeat})")
    return check.unsure(v, owner["missing"]) if owner.get("missing") else v


def classify(run: dict, units: list[dict], ctx: dict) -> list[dict]:
    """The verdicts of a finished run's red units (read.units), each rechecked (run_triage_check.recheck)."""
    out = []
    for unit in units:
        f = read.facts(unit["lines"])
        if not f["errors"]:
            v = verdict(run, unit, None, f, ctx)
            out.append(v if v["kind"] in QUIET else check.unsure(v, "an error line in the job's failed log"))
            continue
        quiet = (read.needs_red(unit["job"], ctx.get("graph") or {}, ctx.get("red") or []) or f["transient"]
                 or unit.get("unserved") or f["budget"] or flake_of(unit, ctx.get("others")))
        for spec in ([None] if quiet else f["specs"] or [None]):
            out.append(verdict(run, unit, spec, f, ctx))
    return [check.settle(v) for v in out]


def triage(run: dict, jobs: list[dict], log: str, ctx: dict) -> dict:
    """{run, verdicts, dedup}: every red unit of the finished run placed; `dedup` (open orders, hitched wagons,
    running plans) is carried for the dispatch (step 2)."""
    ctx = {**ctx, "red": [j["name"] for j in read.counted(jobs)]}
    verdicts = classify(run, read.units(jobs, log), ctx)
    return {"run": run, "verdicts": verdicts, "dedup": ctx.get("dedup") or {}}
