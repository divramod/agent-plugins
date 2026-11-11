"""The Mac's install job as a farmer finding (hal2 plan 0755 D28, D29, D30, D46): since `f3-01-macos-install` is a job of the
land run again, its result is the delivery's state; the tick reads it from the newest land run whose merge is green.

Run by the `ci` duty (`duties.plan_ci`), read-only: the runs list and that run's jobs through `mtm_ci` and `gh_runs`
(one gh call each per round, shared with the other readers). Findings:

  red    the job ended `failure` or `timed_out`: one wake (the failed steps, the run's link) and one push-only
         `alarm.py deliver-red`, each keyed by the delivered sha, so a red sha reaches the user once (alarm.py's way:
         the farmer's log remembers the key; a later sha that is red pushes again)
  stuck  the job ended `cancelled` although the merge is green: the guard `h1-02-hz-host-install-mac-guard` closed the run because
         the Mac's host runner never took the job (it stayed queued 15 min); same wake and push, keyed by the sha

Anything else (success, skipped, still running, no such job) is no finding. Nothing here writes. `run_json(args, cwd)`
is for tests. Never raises: an unreadable run list is no finding.
"""

import sys
from pathlib import Path

import ci_scan
import gh_runs
import mtm_ci
from tick import act

JOBS = {"macos-install", "install-mac"}  # the job part of f3-01-macos-install (mtm_ci.job_part), past runs' install-mac
ALARM = Path(__file__).resolve().parent / "alarm.py"
CASE = "deliver-red"  # not one of alarm.STUCK: a push, no ring
RED = {"failure": "red", "timed_out": "red", "cancelled": "stuck"}
LOOK = 5  # the newest land runs looked at: the first with a green merge decides


def text_of(value, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit]


def newest(run_json, main: str) -> tuple[dict, dict] | None:
    """(run, the install job) of the newest land run with a green merge and an install job, else None."""
    runs = [r for r in mtm_ci.runs_of(run_json, main) if mtm_ci.landing_of(r.get("headBranch") or "")][:LOOK]
    jobs = gh_runs.jobs([r["databaseId"] for r in runs],
                        {r["databaseId"] for r in runs if r.get("status") == "completed"},
                        gh_runs.view_jobs(run_json, main))
    for r in runs:
        got = jobs.get(r["databaseId"], [])
        if mtm_ci.merged(got):
            job = next((j for j in got if mtm_ci.job_part(j.get("name", "")) in JOBS), None)
            return (r, job) if job else None
    return None


def plan(ctx: dict, run_json=None) -> list[dict]:
    """The delivery's acts for this round (see the module doc); [] when all is well or nothing can be read."""
    main = ctx.get("main") or ""
    if not main:
        return []
    if run_json is None:
        run_json = ci_scan.run_json
    found = newest(run_json, main)
    kind = RED.get(found[1].get("conclusion") or "") if found else None
    if kind is None:
        return []
    run, job = found
    sha = text_of(run.get("headSha") or "unknown", 60)
    failed = [text_of(s.get("name"), 80) for s in job.get("steps") or [] if s.get("conclusion") == "failure"]
    what = ("is red" + (f": {', '.join(failed)}" if failed else "")) if kind == "red" else \
        "never started: the Mac's host runner did not take the job in 15 minutes, the guard closed the run"
    line = f"the Mac's install {job.get('name')} of {sha[:10]} {what}, run {text_of(run.get('url'))}"
    return [act("delivery", kind, "wake", key=f"deliver-{kind}:{sha}", text=line,
                evidence={"sha": sha, "run": run.get("databaseId"), "job": job.get("name"),
                          "conclusion": job.get("conclusion"), "failed": failed}),
            act("delivery", "alarm", "run", key=f"deliver-alarm:{sha}", text=f"alarm: {line}",
                argv=[sys.executable, str(ALARM), CASE, line, "--repo", main])]
