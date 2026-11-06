#!/usr/bin/env python3
"""What a land run's gate is doing right now, for the queue watch (hal2 plan 0695 step 27, D33 F5; train 56-5's run
42106776290: 3/18 green after 49 min, every runner busy, jobs still finishing = a slow lane, not a stall).

  gate_state(run_url, now, run_json) -> {"idle_min", "waits_beside_idle", "busy"} or None (GitHub did not answer)

`idle_min`: minutes since any job of the run last started or finished. `waits_beside_idle`: a job queued longer than
WAIT_MIN whose labels an online, idle runner has (it would take it; nothing does). Read-only: two `gh api` GETs
through `run_json(argv, cwd)` (mtm_scan.run_json; injected in tests). The caller judges (queue_watch.findings).
"""

import datetime as dt
import re

import roletime

MOVE_MIN = 15  # no job started or finished this long = the gate does not move
WAIT_MIN = 5  # a job queued this long beside an idle runner that has its labels = nothing picks it up
JOBS = "repos/{{owner}}/{{repo}}/actions/runs/{run}/jobs?per_page=100"
RUNNERS = "repos/{owner}/{repo}/actions/runners?per_page=100"


def run_id(url) -> str | None:
    m = re.search(r"/runs?/(\d+)", str(url or ""))
    return m.group(1) if m else None


def labels(item: dict) -> set[str]:
    return {str(x.get("name") if isinstance(x, dict) else x).lower() for x in item.get("labels") or []}


def gate_state(url, now: dt.datetime, run_json, cwd: str | None = None) -> dict | None:
    run = run_id(url)
    jobs = (run_json(["gh", "api", JOBS.format(run=run)], cwd) or {}).get("jobs") if run else None
    runners = (run_json(["gh", "api", RUNNERS], cwd) or {}).get("runners")
    if not isinstance(jobs, list) or not isinstance(runners, list):
        return None
    now = roletime.aware(now)
    stamps = [roletime.parse(j.get(k)) for j in jobs for k in ("started_at", "completed_at")]
    last = max((s for s in stamps if s), default=None)
    free = [labels(r) for r in runners if r.get("status") == "online" and not r.get("busy")]
    waits = any(j.get("status") == "queued" and (now - (roletime.parse(j.get("created_at")) or now)).total_seconds()
                > WAIT_MIN * 60 and any(labels(j) <= f for f in free) for j in jobs)
    return {"idle_min": (now - last).total_seconds() / 60 if last else None, "waits_beside_idle": waits,
            "busy": not free}
