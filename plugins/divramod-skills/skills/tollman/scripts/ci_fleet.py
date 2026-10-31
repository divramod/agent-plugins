#!/usr/bin/env python3
"""What the tollman reads of the CI/CD fleet (hal2 plan 0383 step 11, D12, D13); read-only against GitHub and the
CI supervisor's journal, plus the one thing it writes: a request for the supervisor to wake a parked machine.

- the runners of `.github/hal2-runners.toml` (code, labels; the machine is the code's first part: `hz01-host-a`), and
  for a job the barn's list cannot serve also the standing train's own list (`train_catalog`, L91: a car renamed the
  runner codes, so the train's labels were unknown to the barn's list)
- the runners GitHub lists (`gh api repos/{owner}/{repo}/actions/runners`: status, busy)
- the queued jobs of the live landing runs (`gh api .../actions/runs/<id>/jobs`: name, labels, created_at)
- the supervisor's power journal (`<state root>/ci-supervisor/power.log`): a cloud machine's last state, `parked`
  or `up`, and whether a wake order is under way. GitHub lists a parked server online for minutes, so a cloud
  machine counts only by the journal's word (the supervisor's own rule, hal2-ci-supervisor README: "the cloud,
  never GitHub's runner status")
- the wake request: the tollman never wakes a machine itself (record park-the-linux-runner-asap: "Only the CI
  supervisor MUST wake and park CI machines"); it leaves `<state root>/ci-supervisor/wake-requests/<machine>.json`
  (`request`) for the supervisor, which reads it on its next look and answers by wake or by deleting it (plan 0383
  step 12). Nothing in a request is a command: the supervisor verifies it with a fresh look of its own.

The state root is `$HAL2_STATE_DIR`, else `$XDG_STATE_HOME/hal2`, else `~/.local/state/hal2` (hal2-core's paths).
"""

import datetime as dt
import json
import os
import re
import tomllib
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_ci
import mtm_scan

TOML = ".github/hal2-runners.toml"
LOG_TAIL = 256 * 1024  # bytes of the journal read: a machine's last state is always near its end
SAYS = re.compile(r"^(\S+) (\w+): (?:hetzner|azure) says (\w+)")
WAKE = re.compile(r"^(\S+) (\w+): wake \(.*\): ok")
LIVE = ("queued", "in_progress", "waiting", "pending", "requested")
ASLEEP = ("parked", "stopped", "deallocated", "off")
PAGES = 5  # pages of 100 jobs read for one run


def state_root(env=None) -> Path:
    env = os.environ if env is None else env
    if env.get("HAL2_STATE_DIR"):
        return Path(env["HAL2_STATE_DIR"])
    if env.get("XDG_STATE_HOME"):
        return Path(env["XDG_STATE_HOME"]) / "hal2"
    return Path(env.get("HOME") or Path.home()) / ".local/state/hal2"


def supervisor_dir() -> Path:
    return state_root() / "ci-supervisor"


def catalog(main: str) -> list[dict]:
    """The runners of hal2-runners.toml: {code, name, machine, kind, labels (lower case)}; [] without the file."""
    try:
        doc = tomllib.loads((Path(main) / TOML).read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return []
    out = []
    for r in doc.get("runners", []):
        parts = str(r.get("code") or "").split("-")
        out.append({"code": r.get("code"), "name": r.get("name"), "machine": parts[0],
                    "kind": parts[1] if len(parts) > 1 else "", "labels": {str(x).lower() for x in r.get("labels", [])}})
    return out


def train_catalog(main: str, known: set[str]) -> list[dict]:
    """The runners of the standing train's worktree (its carrier) that the barn's list lacks (codes not in `known`);
    [] without a standing train or its worktree."""
    import train_state
    wt = (train_state.standing(train_state.lines(main)) or {}).get("worktree")
    return [r for r in catalog(wt) if r["code"] not in known] if wt and Path(wt).is_dir() else []


def machines(text: str) -> dict[str, dict]:
    """Each cloud machine's last state from the power journal: {machine: {state, at, waking}}; `waking`: a wake order
    answered `ok` after that state, the machine is on its way up."""
    out: dict[str, dict] = {}
    for line in text.splitlines():
        if m := SAYS.match(line):
            out[m[2]] = {"state": m[3], "at": m[1], "waking": False}
        elif (m := WAKE.match(line)) and m[2] in out:
            out[m[2]]["waking"] = True
    return out


def power(path: Path | None = None) -> dict[str, dict]:
    """`machines` of the journal's tail; {} when it does not exist (no supervisor: no cloud machine is known)."""
    path = path or supervisor_dir() / "power.log"
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - LOG_TAIL))
            return machines(f.read().decode("utf-8", "replace"))
    except OSError:
        return {}


def github_runners(run_json, main: str) -> dict[str, dict] | None:
    """The runners GitHub lists by name: {name: {status, busy}}; None when GitHub did not answer (nothing is judged)."""
    doc = run_json(["gh", "api", "repos/{owner}/{repo}/actions/runners?per_page=100"], main)
    if not isinstance(doc, dict) or "runners" not in doc:
        return None
    return {r.get("name"): {"status": r.get("status"), "busy": bool(r.get("busy"))} for r in doc["runners"]}


def queued_jobs(run_json, main: str) -> list[dict]:
    """The queued jobs of the unfinished landing runs: {run, job, name, labels (lower case), created}."""
    out = []
    for r in mtm_ci.runs_of(run_json, main):
        if r.get("status") == "completed":
            continue
        for page in range(1, PAGES + 1):
            url = f"repos/{{owner}}/{{repo}}/actions/runs/{r['databaseId']}/jobs?per_page=100&page={page}"
            doc = run_json(["gh", "api", url], main)
            jobs = (doc or {}).get("jobs") or []
            out += [{"run": str(r["databaseId"]), "job": str(j.get("id")), "name": j.get("name"),
                     "labels": {str(x).lower() for x in j.get("labels", [])}, "created": j.get("created_at")}
                    for j in jobs if j.get("status") == "queued"]
            if len(jobs) < 100:
                break
    return out


def parse_time(text: str | None) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def request_path(machine: str) -> Path:
    return supervisor_dir() / "wake-requests" / f"{machine}.json"


def request(machine: str, job: dict, why: str, now: dt.datetime) -> Path:
    """Leave the supervisor the wake request for `machine` (kept as it is when one stands: the earliest wins). The
    JSON: {schema 1, machine, requested (UTC), by "tollman", run, job, job_name, labels, why}."""
    path = request_path(machine)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"schema": 1, "machine": machine, "requested": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                   "by": "tollman", "run": job["run"], "job": job["job"], "job_name": job["name"],
                                   "labels": sorted(job["labels"]), "why": why}, indent=1) + "\n")
        os.replace(tmp, path)
    return path


def withdraw(keep: set[str]) -> None:
    """Remove the tollman's requests of machines no queued job needs any more (the supervisor deletes the ones it
    answered itself); a request of another author stays."""
    for f in (supervisor_dir() / "wake-requests").glob("*.json") if (supervisor_dir() / "wake-requests").is_dir() else []:
        try:
            if f.stem not in keep and json.loads(f.read_text()).get("by") == "tollman":
                f.unlink()
        except (OSError, json.JSONDecodeError):
            pass
