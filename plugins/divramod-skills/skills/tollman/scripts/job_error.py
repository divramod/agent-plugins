"""A red job's first error line (hal2 plan 0383 steps 4 and 5): what the watch's `job failed: <job>: <line>` event
names (watch_events.py) and what an early fix order gives as its why (early_order.py). The line is the first error
line of the job's failed log (`gh run view --job <id> --log-failed` when gh gives it, else the run's failed log), else
its first non-empty line, else the name of the job's first failed step."""

import re

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan

WIDTH = 160  # an event line's error part
ERROR = re.compile(r"error|failed|failure|fatal|panic|assert|exception|denied|timed out", re.I)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s*")


def clean(line: str) -> str:
    """One log line without its job/step/time columns and colours, cut to a line's width."""
    text = ANSI.sub("", line.split("\t", 2)[-1]).strip()
    return STAMP.sub("", text)[:WIDTH]


def first_error(main: str, rid: str, job: dict, log: str | None) -> str:
    """The job's first error line: its failed log when gh gives it (a run's log is out once it completed, a job's
    once the job did), else the name of its first failed step."""
    if job.get("databaseId"):
        log = mtm_scan.run(["gh", "run", "view", "--job", str(job["databaseId"]), "--log-failed"], main) or log
    mine = [l for l in (log or "").splitlines() if l.startswith(job.get("name", "") + "\t")] or (log or "").splitlines()
    hit = next((l for l in mine if ERROR.search(clean(l))), None) or next((l for l in mine if clean(l)), None)
    if hit:
        return clean(hit)
    step = next((s.get("name") for s in job.get("steps") or [] if s.get("conclusion") in ("failure", "timed_out")), None)
    return f"step {step} failed" if step else "no log yet"
