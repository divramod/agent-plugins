"""The planning half of a finished land run's wired triage (hal2 plan 0490 step 3; run_triage_wire.py runs it in its
detached child): the round's context (live fields, the log's keys), the run's train and the train standing now, the
dedup data (the standing train's open orders and post orders, the hitched wagons), then run_triage_gather.gather,
run_triage.triage and run_triage_act.actions; plus a board note for each moved lane that ran slow (proof_lanes.slow,
L86). Returns the run's signatures (a later run's repeat check), its reds as the waiting push reads them
(fix_wait.compact, plan 0490 step 21) and the planned actions, as data."""

import datetime as dt
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path; board.py lives there)
import fix_wait
import gh_runs
import mtm_scan
import proof_lanes
import run_triage
import run_triage_act
import run_triage_dedup
import run_triage_gather as gather_
import run_triage_read as read
import train_state
from tick import act

QUEUE = ["hal2-cli-git", "worktree", "queue", "--json"]


def context(top: str, main: str) -> dict:
    """The round's context (tick.context with the tollman's wiring): panes by field and the log."""
    import tick
    import tollman
    return tick.context(top, main, {}, dt.datetime.now(), False, tollman.WIRING)


def dedup_of(standing: dict | None, tickets: list[dict]) -> dict:
    """run_triage_dedup's data: the open orders of the train standing (`orders` and `post`) and the hitched wagons."""
    s = standing or {}
    return {"orders": list(s.get("orders") or []) + list(s.get("post") or []),
            "wagons": run_triage_dedup.wagons(tickets)}


def plan(top: str, main: str, url: str, name: str | None, ctx: dict | None, kept: dict, field: str | None,
         now: dt.datetime, train_of, gather=gather_.gather) -> dict:
    """{units, actions} of the finished run at `url` of the train `name` (see the module doc); `kept`: {run id: its
    signatures} of the runs triaged before; `train_of(rows, name)`: (the run's train, the train standing now)."""
    ctx = ctx if ctx is not None else context(top, main)
    train, standing = train_of(train_state.lines(main), name)
    tickets = (mtm_scan.run_json(QUEUE, main) or {}).get("queue", [])
    data = gather(main, train, url, ctx.get("panes") or {}, pipeline_field=field, dedup=dedup_of(standing, tickets),
                  kept=kept)
    if not data:
        return {"units": {}, "actions": []}
    run, jobs, log, rctx = data
    result = run_triage.triage(run, jobs, log, rctx)
    done = {e.get("key") for e in ctx.get("log") or [] if e.get("key")}
    actions = run_triage_act.actions(top, main, result, train, standing, ctx.get("panes") or {}, done)
    return {"units": read.signatures(jobs, log), "reds": fix_wait.compact(result["verdicts"], run.get("at")),
            "actions": actions + slow(top, main, train, run, jobs, rctx.get("moved") or {}, now)}


def timed(job: dict) -> dict:
    """A job of `gh run view --json jobs` (startedAt, completedAt) in proof_lanes' API shape."""
    return {**job, "started_at": job.get("started_at") or job.get("startedAt"),
            "completed_at": job.get("completed_at") or job.get("completedAt")}


def slow(top: str, main: str, train: dict, run: dict, jobs: list[dict], moved: dict, now: dt.datetime) -> list[dict]:
    """L86: a board note per job whose lane a car moved and that ran over proof_lanes.FACTOR times its time in the
    last green land run (one more jobs read, of a completed run: gh_runs' cache); none without a moved lane."""
    if not moved:
        return []
    rid = str(run.get("id"))
    green = next((r for r in gather_.land_runs(main) if r.get("conclusion") == "success"
                  and str(r.get("databaseId")) != rid), None)
    if not green:
        return []
    gid = str(green["databaseId"])
    was = gh_runs.jobs([gid], {gid}, gh_runs.view_jobs(mtm_scan.run_json, main)).get(gid) or []
    out = []
    for hit in proof_lanes.slow(moved, [timed(j) for j in jobs], [timed(j) for j in was], now):
        text = (f"{hit['job']} of {run.get('url')} ran {hit['secs']} s, over {proof_lanes.FACTOR}x its "
                f"{hit['green_secs']} s in the last green run, on {hit['runner'] or 'an unknown runner'}: its lane was "
                f"moved by car {', '.join(hit['cars'])} (L86)")
        argv = [sys.executable, str(farmer_frame.SCRIPTS / "board.py"), "post", "--kind", "note", "--from",
                Path(top).name, "--to", hit["cars"][0] if len(hit["cars"]) == 1 else "-", "--train", train["train"],
                "--repo", top, "--text", text]
        out.append(act("trains", "triage-slow", "run", "-", key=f"triage-slow:{rid}:{hit['job']}", argv=argv,
                       text=text))
    return out
