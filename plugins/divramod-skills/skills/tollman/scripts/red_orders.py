#!/usr/bin/env python3
"""Every red job of a land run has its fix order, or a named reason (the user, 2026-11-04: "do you write down in a log,
to which foreman you send a fix order already? ... in your handoff, you then just should run a script, which checks,
if you have send a foreman to fix a red job, for each of the red jobs"; "this also needs to be bullet proof").

The log is `train.jsonl`: each fix order is an `order` line (field, id, run, jobs, why; an `also` line adds jobs to an
open order), each answer a `fixed` line. This script only reads it against GitHub's own job list of the run, never
against the triage (the triage can miss a job: a wake closed unread, a cut-off session). Per red job, the first that
holds:

- `ordered`: an order line of that run whose `jobs` names the job (or, for an older line, whose `why` names it), with
  `fixed <sha>` once its `fixed` line is there, else `open`;
- `reason`: a named reason of that run (`red_orders.py reason`, kept in run-triage.json's `job_reasons`; fix_wait's
  `reasons["*"]` counts for every job), or the run triage's own quiet verdict for the job (runner, flake, needs-red);
- `runner retry`: the train was landed again after a runner fault (a `retry` line after the run);
- else `MISSING`: nobody was told. The exit is 1 then, 3 when a run's jobs cannot be read (never a silent green),
  else 0. The `gate` job is the sum of the others and needs no order.

Runs: `--run` (repeatable), else every land run of the standing train (its `run` lines), else the land run of the
train landed last.

  red_orders.py check [--repo <dir>] [--run <url|id>]... [--json]
  red_orders.py reason [--repo <dir>] --run <url|id> --job <job> --why <text>
"""

import argparse
import json
import sys

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_ci
import mtm_scan
import run_triage_wire as wire
import stack_red
import train_state

QUIET = ("needs-red", "runner", "flake")  # the run triage's kinds that are not ours to fix (fix_wait.QUIET)
ALL = "*"
OK, MISSING, UNREADABLE = 0, 1, 3


def rid_of(url) -> str:
    return str(url or "").rstrip("/").rsplit("/", 1)[-1]


def fetch_jobs(main: str, rid: str) -> list[dict] | None:
    """The run's jobs from GitHub, None when they cannot be read."""
    doc = mtm_scan.run_json(["gh", "run", "view", rid, "--json", "jobs"], main)
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    return jobs if isinstance(jobs, list) else None


def runs(rows: list[dict], asked: list[str]) -> list[str]:
    """The runs to check: the asked ones, else the standing train's land runs, else the last landed train's."""
    if asked:
        return list(dict.fromkeys(rid_of(r) for r in asked))
    train = train_state.standing(rows)
    if train:
        return list(dict.fromkeys(rid_of(e["run"]) for e in rows
                                  if e.get("kind") == "run" and e.get("train") == train["train"] and e.get("run")))
    landed = [e for e in rows if e.get("kind") == "landed" and e.get("run")]
    return [rid_of(landed[-1]["run"])] if landed else []


def names(job: str) -> set[str]:
    """The names an order may know a job by: its display name and its bare gate job."""
    return {job, stack_red.bare(job)}


def cover(job: str, rid: str, rows: list[dict], entry: dict) -> dict:
    """The verdict for one red job of run `rid` (see the module doc)."""
    known = names(job)
    orders = [e for e in rows if e.get("kind") == "order" and rid_of(e.get("run")) == rid]
    hits = [e for e in orders if known & set(e.get("jobs") or [])]
    hits = hits or [e for e in orders if any(n in str(e.get("why") or "") for n in known)]
    if hits:
        fixed = {e.get("id"): e for e in rows if e.get("kind") == "fixed"}
        out = []
        for oid in dict.fromkeys(e.get("also") or e.get("id") for e in hits):
            field = next(e.get("field") for e in hits if (e.get("also") or e.get("id")) == oid)
            done = fixed.get(oid)
            out.append({"id": oid, "field": field,
                        "state": f"fixed {str(done.get('sha') or '')[:10]}".strip() if done else "open"})
        return {"job": job, "verdict": "ordered", "orders": out}
    reasons = entry.get("job_reasons") or {}
    why = next((reasons[n] for n in known if n in reasons), None) or (entry.get("reasons") or {}).get(ALL)
    if why:
        return {"job": job, "verdict": "reason", "why": why}
    quiet = [r for r in entry.get("reds") or [] if r.get("kind") in QUIET and names(r.get("job") or "") & known]
    if quiet:
        return {"job": job, "verdict": "reason", "why": f"run triage: {quiet[0]['kind']}"}
    if any(e.get("kind") == "retry" and str(e.get("why", "")).startswith(train_state.RUNNER)
           and rid in str(e.get("why", "")) for e in rows):
        return {"job": job, "verdict": "runner retry"}
    return {"job": job, "verdict": "MISSING"}


def check(main: str, asked: list[str] | None = None, read=None, entries=None) -> dict:
    """{runs: [{run, status, reds: [verdict]}], missing: n, unreadable: n}."""
    rows = train_state.lines(main)
    read = read or (lambda rid: fetch_jobs(main, rid))
    entries = entries or (lambda rid: next((r for r in wire.state(main)["runs"] if r.get("run") == rid), {}))
    out = {"runs": [], "missing": 0, "unreadable": 0}
    for rid in runs(rows, asked or []):
        jobs = read(rid)
        if jobs is None:
            out["unreadable"] += 1
            out["runs"].append({"run": rid, "status": "unreadable", "reds": []})
            continue
        reds = [j for j in mtm_ci.red_jobs(jobs) if mtm_ci.job_part(j) != "gate"]
        running = any(j.get("status") != "completed" for j in jobs)
        verdicts = [cover(j, rid, rows, entries(rid)) for j in reds]
        out["missing"] += sum(v["verdict"] == "MISSING" for v in verdicts)
        out["runs"].append({"run": rid, "status": "running" if running else "completed", "reds": verdicts})
    return out


def lines(result: dict) -> list[str]:
    out = []
    for r in result["runs"]:
        if r["status"] == "unreadable":
            out.append(f"run {r['run']}: UNREADABLE: its jobs could not be read from GitHub; check again")
            continue
        out.append(f"run {r['run']} ({r['status']}): {len(r['reds'])} red job(s)")
        for v in r["reds"]:
            if v["verdict"] == "ordered":
                told = ", ".join(f"{o['id']} to {o['field']} ({o['state']})" for o in v["orders"])
                out.append(f"  {v['job']}: ordered: {told}")
            elif v["verdict"] == "reason":
                out.append(f"  {v['job']}: reason: {v['why']}")
            elif v["verdict"] == "runner retry":
                out.append(f"  {v['job']}: runner retry")
            else:
                out.append(f"  {v['job']}: MISSING: no fix order, no reason: triage it, then `tollman.py order "
                           f"<field> --run {r['run']} --job {stack_red.bare(v['job'])} --why ...` or "
                           f"`red_orders.py reason --run {r['run']} --job {stack_red.bare(v['job'])} --why ...`")
    if not result["runs"]:
        out.append("red orders: no land run to check")
    elif not result["missing"] and not result["unreadable"]:
        out.append("red orders: every red job has its fix order or a reason")
    return out


def exit_code(result: dict) -> int:
    return UNREADABLE if result["unreadable"] else MISSING if result["missing"] else OK


def reason(main: str, run: str, job: str, why: str) -> str:
    rid = rid_of(run)
    wire.update(main, rid, lambda e: e.setdefault("job_reasons", {}).update({stack_red.bare(job): why}))
    return rid


def report(repo: str) -> int:
    """The check's lines for `act` and `handoff`; never raises (the caller's own work goes on)."""
    try:
        result = check(mtm_scan.main_checkout(repo))
    except Exception as e:  # noqa: BLE001 (a report must not break act or handoff; it says it failed)
        print(f"red orders: CHECK FAILED ({e}): run `python3 red_orders.py check` by hand")
        return UNREADABLE
    print("\n".join(lines(result)))
    return exit_code(result)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("check", "reason"))
    p.add_argument("--repo", default=".")
    p.add_argument("--run", action="append", default=[])
    p.add_argument("--job")
    p.add_argument("--why")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    main_ = mtm_scan.main_checkout(a.repo)
    if a.cmd == "reason":
        if len(a.run) != 1 or not a.job or not a.why:
            p.error("reason needs one --run, --job and --why")
        rid = reason(main_, a.run[0], a.job, a.why)
        print(f"run {rid}: {stack_red.bare(a.job)} has a named reason ({a.why})")
        return OK
    result = check(main_, a.run)
    print(json.dumps(result, indent=1) if a.json else "\n".join(lines(result)))
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
