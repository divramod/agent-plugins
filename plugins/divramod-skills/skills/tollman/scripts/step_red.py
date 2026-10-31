"""A red step of a job that still runs (hal2 plan 0490 step 25, D25; open-train-brief.md point 5): the 1-minute watch
(watch_events.collect) sees `[06] gate stack-test hub-e2e` fail while `[13]` of the same job still runs, an hour
before the job's own red. `events` gives one `step-failed` event per red step, `step failed: <job> <step>`, keyed
`step:<run>:<job>:<step>` (watch_events keeps the told keys: once); run_triage_step_act.py triages and orders it.

The read (D9): only while a job of the run is `in_progress` by the pass's own jobs read (`gh run view --json jobs`,
already made), one `gh api .../actions/runs/<run>/jobs` list a pass (a page per 100 jobs, ci_fleet.queued_jobs'
call; gh_runs.memo: once per round), never a call when nothing runs. The API's jobs carry what the run view's do not:
each step's `completed_at` and `started_at` and the job's `runner_name`. Every event also carries the merge job's
green time (`merged_at`), so the order's target train follows when the step failed (before or after the merge).
"""

import datetime as dt

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import gh_runs
import mtm_ci
import mtm_scan
import run_triage_read as read

API = "repos/{{owner}}/{{repo}}/actions/runs/{rid}/jobs?per_page=100&page={page}"
PAGES = 3
KIND = "step-failed"


def running(jobs: list[dict]) -> bool:
    """A job of the run is still running (the pass's run view): only then the steps are read."""
    return any(j.get("status") == "in_progress" for j in jobs or [])


def api_jobs(main: str, rid: str, run_json=None) -> list[dict]:
    """The run's jobs as GitHub's jobs list gives them (steps with times, runner_name), once per round."""
    run_json = run_json or mtm_scan.run_json

    def fetch() -> list[dict]:
        out = []
        for page in range(1, PAGES + 1):
            got = (run_json(["gh", "api", API.format(rid=rid, page=page)], main) or {}).get("jobs") or []
            out += got
            if len(got) < 100:
                break
        return out
    return gh_runs.memo(("step-red-jobs", str(rid)), fetch)


def secs(step: dict) -> int | None:
    """A step's wall time in seconds, None when a time is missing."""
    try:
        a, b = (dt.datetime.fromisoformat(str(step[k]).replace("Z", "+00:00")) for k in ("started_at", "completed_at"))
    except (KeyError, TypeError, ValueError):
        return None
    return max(0, int((b - a).total_seconds()))


def merged_at(jobs: list[dict]) -> str | None:
    """When the merge job went green (its `completed_at`), else None: the landing's merge into main."""
    return next((j.get("completed_at") for j in jobs if mtm_ci.job_part(j.get("name", "")) in mtm_ci.MERGE_JOBS
                 and j.get("conclusion") == "success"), None)


def watched(job: dict) -> bool:
    """A running job whose red steps count: not the merge or park job, not a lane's stop job."""
    name = job.get("name", "")
    return job.get("status") == "in_progress" and mtm_ci.job_part(name) not in mtm_ci.NOT_COUNTED \
        and not mtm_ci.stop_job(job)


def events(main: str, rid: str, url: str | None, jobs: list[dict], row: dict | None = None,
           run_json=None) -> list[dict]:
    """The `step-failed` events of the run's running jobs (all of them; watch_events drops the told)."""
    if not running(jobs):
        return []
    api = api_jobs(main, rid, run_json)
    merged, out = merged_at(api), []
    for j in (j for j in api if watched(j)):
        for s in read.failed_steps(j):
            name, step = j.get("name", ""), s.get("name", "")
            out.append({"key": f"step:{rid}:{name}:{step}", "kind": KIND, "text": f"step failed: {name} {step}",
                        "run": str(rid), "url": url, "job": name, "job_id": str(j.get("id") or ""), "step": step,
                        "at": s.get("completed_at"), "secs": secs(s), "runner": j.get("runner_name") or "",
                        "merged_at": merged, "created": (row or {}).get("createdAt"),
                        "sha": (row or {}).get("headSha")})
    return out
