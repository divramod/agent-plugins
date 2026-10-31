#!/usr/bin/env python3
"""A car's lane moves: the jobs whose `runs-on` its crop changes in `.github/workflows/` (hal2 plan 0490 step 7).

- `check` (proof.py's light check `lanes`, L70): a job the crop routes to labels no runner of the barn's
  `.github/hal2-runners.toml` has rides only when a runner with them is online on GitHub; else the car is red (the
  barn's CI supervisor cannot wake a runner it does not know: keep the old runs-on until the runner is in the barn).
  It runs only for a crop that changes a workflow, and asks GitHub only for labels the barn's list lacks.
- `moved_by` and `mover` (L83, L87): the car whose crop moved a red job's lane owns that red, a post-merge delivery
  red (e*, f*) too; git only, for the run's triage.
- `slow` (L86): a moved job, finished or still running, over FACTOR times the same job's time in the last green
  train is flagged with the car that moved it.

A job is keyed by its stage (`c3`): a lane move renames the job id (`c3-hz01-host-b` -> `c3-az03-host-b`), the stage
stays; a job without a stage is keyed by its id. Labels compare in lower case; a job without `self-hosted` runs on
GitHub's runners and is never judged, nor is a `runs-on` that is an expression.
"""

import datetime as dt
import json
import re
import tomllib

WORKFLOW = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")
RUNNERS = ".github/hal2-runners.toml"
STAGE = re.compile(r"^([a-z][1-9])-")
FACTOR = 2  # a moved job slower than this many times its last green time is flagged (L86)


def key(job: str) -> str:
    """A job id's or display name's stage (`c3-01-rust-test` -> `c3`), else the id itself."""
    m = STAGE.match(job or "")
    return m[1] if m else job


def labels_of(value: str) -> frozenset | None:
    """The labels of a `runs-on` value (`[a, b]` or `a`); None for an expression or a mapping."""
    value = value.split(" #", 1)[0].strip()
    if not value or "${{" in value or value.startswith("{"):
        return None
    items = value.strip("[]").split(",") if value.startswith("[") else [value]
    got = frozenset(i.strip().strip("'\"").lower() for i in items if i.strip())
    return got or None


def lanes(text: str) -> dict[str, set[frozenset]]:
    """{job key: its runs-on label sets} of a workflow's `jobs:` (inline and block lists, as hal2's workflows write)."""
    out: dict[str, set[frozenset]] = {}
    inside, job, block = False, "", None
    for line in (text or "").splitlines():
        if block is not None:
            if m := re.match(r"^\s{6,}-\s*(.+?)\s*$", line):
                block.append(m[1])
                continue
            if (got := labels_of("[" + ", ".join(block) + "]")) and job:
                out.setdefault(job, set()).add(got)
            block = None
        if re.match(r"^jobs:\s*(#.*)?$", line):
            inside = True
        elif inside and re.match(r"^\S", line):
            inside = False
        elif inside and (m := re.match(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$", line)):
            job = key(m[1])
        elif inside and job and (m := re.match(r"^    runs-on:\s*(.*?)\s*$", line)):
            if not m[1] or m[1].startswith("#"):
                block = []
            elif got := labels_of(m[1]):
                out.setdefault(job, set()).add(got)
    if block and job and (got := labels_of("[" + ", ".join(block) + "]")):
        out.setdefault(job, set()).add(got)
    return out


def show(run, cwd: str, rev: str, path: str) -> str:
    code, text = run(["git", "show", f"{rev}:{path}"], cwd)
    return text if code == 0 else ""


def moves(cwd: str, base: str, head: str, files: list[str], run) -> list[dict]:
    """The crop's lane moves, self-hosted only: [{workflow, job, from: [labels], to: [labels]}]; a new job is a move
    from nothing."""
    out = []
    for wf in sorted(f for f in files if WORKFLOW.match(f)):
        before, after = lanes(show(run, cwd, base, wf)), lanes(show(run, cwd, head, wf))
        for job, sets in sorted(after.items()):
            old = before.get(job, set())
            for to in sorted(sets - old, key=sorted):
                if "self-hosted" in to:
                    out.append({"workflow": wf, "job": job, "from": sorted(min(old, key=sorted)) if old else [],
                                "to": sorted(to)})
    return out


def catalog(text: str) -> list[frozenset]:
    """The label sets of the runners a hal2-runners.toml lists."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    return [frozenset(str(x).lower() for x in r.get("labels", [])) for r in doc.get("runners", [])]


def online(run, cwd: str) -> list[frozenset] | None:
    """The label sets of the runners GitHub lists online; None when GitHub did not answer."""
    code, text = run(["gh", "api", "repos/{owner}/{repo}/actions/runners?per_page=100"], cwd)
    try:
        doc = json.loads(text) if code == 0 else None
    except ValueError:
        doc = None
    if not isinstance(doc, dict) or "runners" not in doc:
        return None
    return [frozenset(str(x.get("name", "")).lower() for x in r.get("labels", []))
            for r in doc["runners"] if r.get("status") == "online"]


def check(field: str, barn: str, head: str, files: list[str], run) -> tuple[int, str]:
    """proof.py's `lanes` check: (0, '') green, (1, finding lines `<workflow>: ...`) red, (127, '') skipped (no runner
    list in the barn, or GitHub silent while a move needs its word)."""
    ms = moves(field, barn, head, files, run)
    if not ms:
        return 0, ""
    known = catalog(show(run, field, barn, RUNNERS))
    if not known:
        return 127, ""
    unknown = [m for m in ms if not any(set(m["to"]) <= r for r in known)]
    if not unknown:
        return 0, ""
    up = online(run, field)
    if up is None:
        return 127, ""
    red = [m for m in unknown if not any(set(m["to"]) <= r for r in up)]
    return (1 if red else 0), "\n".join(
        f"{m['workflow']}: job {m['job']} moves runs-on to [{', '.join(m['to'])}]: no runner of the barn's {RUNNERS} "
        "has these labels and none is online on GitHub; keep the old runs-on until the runner is in the barn (L70)"
        for m in red)


def moved_by(main: str, base: str, cars: list[dict], run) -> dict[str, list[dict]]:
    """{car field: its lane moves} of a train's cars ({field, head}) against the train's base, read in `main`."""
    out = {}
    for car in cars:
        code, text = run(["git", "diff", "--name-only", "--no-renames", f"{base}...{car['head']}", "--",
                          ".github/workflows"], main)
        files = text.splitlines() if code == 0 else []
        if got := moves(main, base, car["head"], files, run):
            out[car["field"]] = got
    return out


def mover(job: str, moved: dict[str, list[dict]]) -> list[str]:
    """The cars that moved the lane of the job `job` (a display name or id): its red is theirs (L83, L87)."""
    stage = key(job)
    return [field for field, ms in moved.items() if any(m["job"] == stage for m in ms)]


def seconds(job: dict, now: dt.datetime) -> float | None:
    def at(text):
        try:
            return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        except ValueError:
            return None
    start = at(job.get("started_at"))
    end = at(job.get("completed_at")) if job.get("completed_at") else now
    return (end - start).total_seconds() if start and end else None


def slow(moved: dict[str, list[dict]], jobs: list[dict], green: list[dict], now: dt.datetime) -> list[dict]:
    """The moved jobs of a run (`jobs`: gh's name, started_at, completed_at, runner_name) over FACTOR times the
    same job's time in the last green train (`green`, successes only): [{job, cars, runner, secs, green_secs}]."""
    was = {j.get("name"): s for j in green if j.get("conclusion") == "success" and (s := seconds(j, now))}
    out = []
    for j in jobs:
        cars, base = mover(j.get("name", ""), moved), was.get(j.get("name"))
        secs = seconds(j, now)
        if cars and base and secs and secs > FACTOR * base:
            out.append({"job": j["name"], "cars": cars, "runner": j.get("runner_name") or "", "secs": round(secs),
                        "green_secs": round(base)})
    return out
