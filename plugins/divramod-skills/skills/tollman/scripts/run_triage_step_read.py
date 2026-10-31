"""The reading half of a red step's triage (hal2 plan 0490 step 25, D25; run_triage_step_act.py acts): the triage's
context for a step red (the train's cars and their files, the live fields, the kept earlier runs' signatures, the
pipeline's field, the dedup data), and the recheck at the job's end, which reads the job's failed log and places its
red by the finished run's rule (run_triage.classify), against the step's verdict. Reads only when a step red or a
step-ordered job's end is fresh: a quiet pass reads nothing here."""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import run_triage_wire as wire
from tick import act

PLACED = ("car", "pipeline", "file", "repeat")  # a verdict that names its owner


def rows(main: str) -> list[dict]:
    import train_state
    return train_state.lines(main)


def round_context(top: str, main: str) -> dict:
    """The round's {panes, log} (run_triage_plan.context: the sessions' list, the tollman's log)."""
    import run_triage_plan
    return run_triage_plan.context(top, main)


def context(top: str, main: str, train: dict, ctx: dict, standing: dict | None, doc: dict) -> dict:
    """run_triage_step.verdict's context and the dedup data (run_triage_plan.dedup_of, the running plans)."""
    import run_triage_gather as g
    import run_triage_plan
    import triage
    cars = triage.car_files(main, train)
    kept = [r for r in wire.state(main)["runs"] if r.get("at") and not r.get("error")]
    return {"cars": cars, "yard": train.get("yard") or [], "live": set(ctx.get("panes") or {}),
            "previous": [{"id": r["run"], "units": r.get("units") or {}} for r in reversed(kept)][:g.PREVIOUS],
            "pipeline_field": wire.pipeline_field(top), "gate_jobs": g.gate_jobs(main), "base": train.get("base"),
            "moved": g.moved(main, train, cars),
            "dedup": {**run_triage_plan.dedup_of(standing, doc.get("queue", [])), "plans": g.plans(main)}}


def rechecked(main: str, fresh: list[dict], watched: dict) -> list[tuple[dict, list[dict]]]:
    """[(a fresh `job failed` event of the watched run, the kept step verdicts of that job an order went out for)]."""
    rid = str(watched.get("run") or "")
    ends = [e for e in fresh if e["kind"] == "job-failed" and rid and e["key"].startswith(f"job:{rid}:")]
    if not ends:
        return []
    entry = next((r for r in wire.state(main)["runs"] if r.get("run") == rid), {})
    out = []
    for e in ends:
        job = e["key"].split(":", 2)[2]
        if kept := [s for s in entry.get("steps") or [] if s.get("ordered") and s.get("job") == job]:
            out.append((e, kept))
    return out


def job_verdicts(main: str, rid: str, url: str, kept: list[dict], train: dict, tctx: dict) -> list[dict]:
    """The finished job's verdicts by the finished run's rule: its failed log (one gh call), its specs' owners."""
    import gh_runs
    import mtm_ci
    import run_triage
    import run_triage_gather as g
    import run_triage_read as read
    job, jid = kept[0]["job"], kept[0].get("job_id")
    jobs = gh_runs.jobs([rid], set(), gh_runs.view_jobs(mtm_scan.run_json, main)).get(rid) or []  # the pass's read
    j = next((x for x in jobs if x.get("name") == job), {"name": job, "conclusion": "failure"})
    log = mtm_scan.run(["gh", "run", "view", "--job", str(jid), "--log-failed"], main) if jid else ""
    units = read.units([j], log or "")
    row = next((r for r in mtm_ci.runs_of(mtm_scan.run_json, main) if str(r.get("databaseId")) == rid), {})
    paths, owners = g.owners(main, row.get("headSha"), units)
    ctx = {**tctx, "paths": paths, "owners": owners, "plans": (tctx.get("dedup") or {}).get("plans") or {},
           "graph": {}, "red": [], "others": []}
    run = {"id": rid, "url": url, "sha": row.get("headSha"), "base": train.get("base")}
    return run_triage.classify(run, units, ctx)


def recheck(top: str, main: str, end: dict, kept: list[dict], train: dict, tctx: dict, done=()) -> list[dict]:
    """The job's end: each kept step verdict an order went out for, rechecked from the job's log (see the module
    doc): the same owner, a record; else one `step-red` wake with both, never a second order."""
    import run_triage_step_act as acts
    import run_triage_text as words
    import stack_red
    rid = end["key"].split(":", 2)[1]
    url = next((r.get("url") for r in wire.state(main)["runs"] if r.get("run") == rid), None) or ""
    verdicts, out = job_verdicts(main, rid, url, kept, train, tctx), []
    for s in kept:
        mine = [v for v in verdicts if v["evidence"].get("unit") == s["unit"]] or verdicts
        same = [v for v in mine if v["kind"] in PLACED and v.get("owner") == s.get("owner")]
        head = f"{s['unit']} (step {s['step']}, ordered to {s.get('owner')})"
        if same:
            out.append(act("trains", "step-record", "record", "-", key=f"{s['key']}:recheck",
                           text=f"{head}: the job's log agrees ({words.how(same[0])}, {words.first(same[0])})"))
            continue
        found = "; ".join(f"{v['kind']} {v.get('owner') or '-'}: {words.first(v)}" for v in mine) or "no red unit"
        out.append(act("trains", acts.KIND, "wake", key=f"{acts.KIND}:{rid}:{stack_red.bare(s['job'])}:recheck",
                       evidence={"run": url, "train": train, "step": s, "verdicts": mine},
                       text=f"tollman: the step order for {head} of {url}: the job's log places it otherwise "
                            f"({found}). Judge it: when the order went to the wrong field, tell {s.get('owner')} by a "
                            f"board note and order the right one (`python3 {acts.CLI} order <field> "
                            f"[--post {train.get('train')}] --why ... --run {url}`)"))
    return [a for a in out if a["key"] not in set(done)]
