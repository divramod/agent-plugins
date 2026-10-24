"""How long each VM job of the last land runs waited for its runner (plan 0391 step 11: under 15 s).

A job's wait is GitHub's started_at minus the later of its created_at and the end of the VM job the VM ran
before it in the same run: a job chained by `needs`, or a matrix's next under `max-parallel: 1`, has its lane's
created_at, so that alone would count the job before as waiting. Pure but `land_runs`, which asks gh.
"""

import json
import statistics
from datetime import datetime

WORKFLOWS = ("merge-to-main-cloud.yml", "merge-to-main-local.yml", "dev-merge-to-main.yml", "merge-to-main.yml")  # plan 0423 D4
TARGET = 15  # seconds: a VM job waits seconds, not minutes (plan 0391 D11)
CODE = "mac-vm-a"  # the VM runner's own label


def when(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def gaps(run, jobs, code=CODE):
    """[(run, job name, wait s, work s or None)] of `run`'s VM jobs that ran, by their start."""
    ran = [j for j in jobs if code in (j.get("labels") or []) and j.get("started_at")
           and j.get("runner_name") and j.get("conclusion") != "skipped"]
    ran.sort(key=lambda j: j["started_at"])
    rows, before = [], None
    for job in ran:
        created, started, ended = when(job["created_at"]), when(job["started_at"]), when(job.get("completed_at"))
        ready = max(created, before) if before else created
        work = (ended - started).total_seconds() if ended else None
        rows.append((run, job["name"], (started - ready).total_seconds(), work))
        before = ended or before
    return rows


def summary(rows, target=TARGET):
    waits = sorted(row[2] for row in rows)
    if not waits:
        return "no VM job ran"
    p90 = waits[max(0, int(len(waits) * 0.9) - 1)]
    under = sum(w < target for w in waits)
    return (f"{len(waits)} VM jobs: median {statistics.median(waits):.0f}s, p90 {p90:.0f}s, "
            f"max {waits[-1]:.0f}s, {under} under {target}s")


def land_runs(run, repo, count):
    """The last `count` land runs as [(run id, its jobs)] through `run` (sources.run); None when gh failed."""
    out = None  # the first name GitHub knows (hal2 lands as the cloud file once renamed)
    for name in WORKFLOWS:
        out = run(["gh", "api", f"repos/{repo}/actions/workflows/{name}/runs?per_page={count}"])
        if out is not None:
            break
    if out is None:
        return None
    found = []
    for rid in [r["id"] for r in json.loads(out)["workflow_runs"]]:
        jobs = run(["gh", "api", f"repos/{repo}/actions/runs/{rid}/jobs?filter=latest&per_page=100"])
        if jobs is None:
            return None
        found.append((rid, json.loads(jobs)["jobs"]))
    return found


def report(found, target=TARGET):
    """The rows' lines and the summary; whether every VM job waited under `target`."""
    rows = [row for rid, jobs in found for row in gaps(rid, jobs)]
    lines = [f"{rid} {name[:32]:32} waited {wait:5.0f}s  worked {work if work is not None else -1:5.0f}s"
             for rid, name, wait, work in rows]
    lines.append(summary(rows, target))
    return lines, all(row[2] < target for row in rows)
