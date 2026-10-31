"""A land-run job past twice its usual time is a fault, not slowness (hal2 plan 0490 step 11, D15, L127: train 27's
c1-02-rust-build-mac ran 3 h, 7 min on 10-28, its rustc at background QoS, and was called slow-but-alive for hours).

The watch (watch_events.py) reads, once per watched run, each job's median time in the last GREEN green land runs
(`base`: the runs list it already reads, their jobs from gh_runs' cache of completed runs) and keeps it with the run;
each minute it flags a job of the live run, running or done, whose time is over FACTOR times its median and at least
FLOOR seconds over it (`events`, from the jobs the watch has fetched anyway: no gh call). One event per job and run,
`slow:<run>:<job>`; the woken tollman looks at the job's runner (nice, QoS, `HAL2_WORKQUEUE_*`, instructions/trains.md).
"""

import datetime as dt
import statistics

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import gh_runs
import mtm_ci
import mtm_scan

FACTOR = 2
FLOOR = 300  # seconds over the median before a job counts: a 40 s job taking 90 s is noise
GREEN = 3  # green land runs the median is taken over


def at(text) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def seconds(job: dict, now: dt.datetime) -> float | None:
    """A job's time (gh's startedAt, completedAt; a running job's up to `now`); None before it started."""
    if job.get("status") not in ("in_progress", "completed"):
        return None
    start = at(job.get("startedAt") or job.get("started_at"))
    end = at(job.get("completedAt") or job.get("completed_at")) if job.get("status") == "completed" else now
    return (end - start).total_seconds() if start and end and end >= start else None


def base(main: str, rid: str, now: dt.datetime) -> dict[str, float]:
    """{job name: its median seconds} over the last GREEN successful land runs but `rid`; {} when none is known."""
    green = [str(r["databaseId"]) for r in mtm_ci.runs_of(mtm_scan.run_json, main)
             if r.get("conclusion") == "success" and str(r.get("databaseId")) != str(rid)][:GREEN]
    if not green:
        return {}
    times: dict[str, list[float]] = {}
    for jobs in gh_runs.jobs(green, set(green), gh_runs.view_jobs(mtm_scan.run_json, main)).values():
        for j in jobs or []:
            if j.get("conclusion") == "success" and (s := seconds(j, now)):
                times.setdefault(j.get("name"), []).append(s)
    return {name: statistics.median(ts) for name, ts in times.items()}


def events(rid: str, jobs: list[dict], medians: dict[str, float], now: dt.datetime) -> list[dict]:
    """The watch's `slow-job` events of the run `rid`: each job over FACTOR times its median and FLOOR over it."""
    out = []
    for j in jobs:
        usual, secs = medians.get(j.get("name")), seconds(j, now)
        if usual and secs and secs > FACTOR * usual and secs - usual >= FLOOR:
            out.append({"key": f"slow:{rid}:{j['name']}", "kind": "slow-job",
                        "text": f"job slow: {j['name']} {'ran' if j.get('status') == 'completed' else 'runs'} "
                                f"{int(secs // 60)} min, over {FACTOR}x its median {int(usual // 60)} min of the last "
                                f"green runs: a fault, not slowness (L127); look at its runner now"})
    return out
