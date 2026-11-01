"""A red job's first error line (hal2 plan 0383 steps 4 and 5): what the watch's `job failed: <job>: <line>` event
names (watch_events.py) and what an early fix order gives as its why (early_order.py). The line is the first error
line of the job's failed log (`job_log`), else the run's failed log, else its first non-empty line, else the name of
the job's first failed step; a test runner's own red line (`not ok`, `FAIL`, `×`, `error:`) comes before a line that
only has an error word in it (train 32's why was `ok 35 ... a failure 1 in 261ms`).

`job_log`: a red job's failed log also while its run still runs (plan 0522 D16). gh gives a run's or a job's failed
log only once the whole run has completed (`gh run view [--job <id>] --log-failed`: "still in progress"), so train 32's
reds of run 41167356202 had no log for 38 minutes and their triage named no car; GitHub's own job log
(`gh api repos/{owner}/{repo}/actions/jobs/<id>/logs`) is out once the job has completed. It is cut to the failed step
(from its `##[group]Run` header to `##[error]Process completed`), kept per job id in the tollman's
`cache/job-logs/<id>.txt` (a completed job's log never changes; files older than KEEP_DAYS go at each write) and once
per round (gh_runs.memo).
"""

import contextlib
import re
import time

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import gh_runs
import mtm_scan

WIDTH = 160  # an event line's error part
ERROR = re.compile(r"error|failed|failure|fatal|panic|assert|exception|denied|timed out", re.I)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s*")
OWN = re.compile(r"^(not ok \d|FAIL\b|× |error(\[\w+\])?: |thread '.*' panicked)")  # a test runner's red line
API = "repos/{{owner}}/{{repo}}/actions/jobs/{id}/logs"
ROLE = "tollman"
CACHE = "job-logs"
KEEP_DAYS = 7
END = "##[error]Process completed with exit code"


def clean(line: str) -> str:
    """One log line without its job/step/time columns and colours, cut to a line's width."""
    text = ANSI.sub("", line.split("\t", 2)[-1]).strip()
    return STAMP.sub("", text)[:WIDTH]


def failed_step(log: str) -> str:
    """The failed step's own lines of a job's whole log (GitHub's `##[group]Run` header and its group left out), or
    the log's last 200 lines when no step says it failed."""
    lines = (log or "").splitlines()
    end = next((i for i, line in enumerate(lines) if END in line), None)
    if end is None:
        return "\n".join(lines[-200:])
    start = next((i for i in range(end - 1, -1, -1) if "##[group]Run " in lines[i]), -1)
    close = next((i for i in range(start + 1, end) if "##[endgroup]" in lines[i]), start) if start >= 0 else -1
    return "\n".join(lines[close + 1:end])


def folder(main: str):
    """`cache/job-logs` of the tollman's state folder, or None when that folder does not exist."""
    state = mtm_scan.state_dir(main, ROLE)
    return state / "cache" / CACHE if state.is_dir() else None


def job_log(main: str, job: dict) -> str:
    """The red job's failed log (see the module doc), or "" (no id, not completed, gh does not answer)."""
    jid = str(job.get("databaseId") or "")
    if not jid or job.get("status") not in (None, "completed"):
        return ""
    return gh_runs.memo(("job-log", jid), lambda: _read(main, jid))


def _read(main: str, jid: str) -> str:
    where = folder(main)
    with contextlib.suppress(OSError):
        if where and (where / f"{jid}.txt").is_file():
            return (where / f"{jid}.txt").read_text()
    text = mtm_scan.run(["gh", "run", "view", "--job", jid, "--log-failed"], main) or failed_step(
        mtm_scan.run(["gh", "api", API.format(id=jid)], main) or "")
    with contextlib.suppress(OSError):
        if where and text:
            where.mkdir(parents=True, exist_ok=True)
            for old in where.glob("*.txt"):
                if time.time() - old.stat().st_mtime > KEEP_DAYS * 86400:
                    old.unlink()
            tmp = where / f".{jid}.tmp"
            tmp.write_text(text)
            tmp.replace(where / f"{jid}.txt")
    return text


def first_error(main: str, rid: str, job: dict, log: str | None) -> str:
    """The job's first error line: its failed log (`job_log`, else the run's `log`), else the name of its first
    failed step."""
    log = job_log(main, job) or log
    mine = [l for l in (log or "").splitlines() if l.startswith(job.get("name", "") + "\t")] or (log or "").splitlines()
    hit = next((l for l in mine if OWN.search(clean(l))), None) or next(
        (l for l in mine if ERROR.search(clean(l))), None) or next((l for l in mine if clean(l)), None)
    if hit:
        return clean(hit)
    step = next((s.get("name") for s in job.get("steps") or [] if s.get("conclusion") in ("failure", "timed_out")), None)
    return f"step {step} failed" if step else "no log yet"
