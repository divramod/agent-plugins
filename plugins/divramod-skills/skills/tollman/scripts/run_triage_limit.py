"""A red job the time limit killed (hal2 plan 0719, learning L267): pure parser, no IO. Train 56-7's run 42133755939
(c6-01-lint) was red only because the gate's own 20-minute limit (`stack_limit`, `timeout`) ended its records-check
step while the state-scratch phase ran slow on a loaded runner: the log ends `##[error]gate: lint: records-check
failed`, `[12] 💥 00:54:51 ⏳ 00:20:00 (exit 1)` and a phase table, with no failing test or error line, and the triage
named a car's order for it. A kill with no finding is the runner's load, never a car's (the record tollman).

`kill(job, lines)` reads the two signals, GitHub's own data first (D2 of plan 0719), and returns the kill or None:

- `github`: the job or one of its steps ended `timed_out`, or the log has GitHub's "exceeded the maximum execution
  time" line (a workflow's `timeout-minutes`)
- `gate`: the step ran one gate step alone (`gate lint --step <name>`: the env lines `LINT:` or `JOB:`), that step
  failed (`gate: <frame>: <name> failed`), the frame declared its limit (HAL_FRAME_STEPS, the log's `STEPS:` JSON,
  `"job": "<name>" ... "timeout": <minutes>`) and the step's `[NN] 💥 hh:mm:ss ⏳ hh:mm:ss` marker shows a duration from
  that limit to SLACK s past it. A step the log does not show declared is never taken for a kill

The kill is {by, step, secs, limit, match}; `match` is the evidence's words (`job limit: records-check after 00:20:00,
the gate's 20 min`). `holds` recomputes it from that record alone (run_triage_check.recheck). Whether a finding
remains (a failing test, an error line that is no frame) is run_triage_read.limit_kill's call.
"""

import re

SLACK = 90  # s past the limit a killed step still runs: `timeout --kill-after=1m`, and the step's own tail
MARK = re.compile(r"^\[\d+\] 💥 \d\d:\d\d:\d\d ⏳ (?P<h>\d+):(?P<m>\d\d):(?P<s>\d\d)")
FAILED = re.compile(r"gate: (?P<frame>[\w-]+): (?P<step>[\w-]+) failed")
TARGET = re.compile(r"^(?:LINT|JOB): (?P<name>[\w-]+)$")
DECLARED = re.compile(r'"job":\s*"(?P<job>[^"]+)",[^{}]*?"timeout":\s*(?P<min>\d+)')
GITHUB = re.compile(r"exceeded the maximum execution time", re.I)
GITHUB_CONCLUSION = "timed_out"


def clock(secs: int) -> str:
    return f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"


def declared(lines: list[str], name: str) -> int:
    """The limit in seconds the log's `STEPS:` JSON declares for step `name`, else 0."""
    found = {m["job"]: int(m["min"]) for m in DECLARED.finditer("\n".join(lines))}
    return found.get(name, 0) * 60


def github(job: dict | None, lines: list[str]) -> dict | None:
    """The kill GitHub's own data shows: a timed_out job or step, or its maximum-execution-time line."""
    job = job or {}
    steps = [s.get("name") or "" for s in job.get("steps") or [] if s.get("conclusion") == GITHUB_CONCLUSION]
    named = steps[0] if steps else job.get("name") or "the job"
    if job.get("conclusion") == GITHUB_CONCLUSION or steps or any(GITHUB.search(t) for t in lines):
        return {"by": "github", "step": named, "secs": 0, "limit": 0,
                "match": f"job limit: {named} ended at GitHub's time limit"}
    return None


def gate(lines: list[str]) -> dict | None:
    """The kill of the one gate step the lines show, by its marker against its declared limit."""
    marks = [m for t in lines if (m := MARK.match(t))]
    fails = [m for t in lines if (m := FAILED.search(t))]
    targets = [m["name"] for t in lines if (m := TARGET.match(t))]
    if not marks or not fails or fails[-1]["step"] not in targets:
        return None
    step, m = fails[-1]["step"], marks[-1]
    secs, limit = int(m["h"]) * 3600 + int(m["m"]) * 60 + int(m["s"]), declared(lines, step)
    if not limit or not limit <= secs <= limit + SLACK:
        return None
    return {"by": "gate", "step": step, "secs": secs, "limit": limit,
            "match": f"job limit: {step} after {clock(secs)}, the gate's {limit // 60} min"}


def kill(job: dict | None, lines: list[str]) -> dict | None:
    """The time-limit kill the job's data and lines show (see the module doc), else None."""
    return github(job, lines) or gate(lines)


def holds(found: dict | None) -> bool:
    """A kill record stands on its own numbers: the gate's step ended from its limit to SLACK s past it; a kill by
    GitHub's own data (timed_out, its line) is the platform's word."""
    if not isinstance(found, dict):
        return False
    if found.get("by") == "github":
        return True
    return 0 < found.get("limit", 0) <= found.get("secs", 0) <= found["limit"] + SLACK
