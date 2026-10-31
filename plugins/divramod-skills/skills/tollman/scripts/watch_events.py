#!/usr/bin/env python3
"""The events of the live land run (hal2 plan 0383 step 4, D4): what the 1-minute duty `watch` (minute.py) prints and
the round (steps 5 and 6) acts on. `new` returns only the events not seen before, one line each:

- `job-failed`: `job failed: <job>: <first error line>` for each red job of the run (mtm_ci.red_jobs: fail-fast
  cancels, ship, build and stop jobs left out); the line is the first error line of the job's failed log, else its
  first failed step
- `step-failed`: `step failed: <job> <step>`, a red step of a job that still runs (step_red.py, plan 0490 step 25,
  D25: one jobs list a pass while a job runs, none else), keyed `step:<run>:<job>:<step>`; run_triage_step_act.py
  triages it and orders its fix at once
- `merge-green`: `merge job green: <job> (<run url>)`, the merge job (`d2-01-git-merge`, mtm_ci.merged)
- `finished`: `workflow finished: <conclusion> (<run url>)`, the run completed
- `slow-job`: `job slow: <job> runs <n> min, over 2x its median ...`, a job past twice its median time in the last
  green land runs (slow_jobs.py, plan 0490 step 11, D15, L127; the medians are read once per run and kept as `base`)

The run is the standing landing train's (watch.find: its branch `land/train-<plans>`, train_branch.py); once noted it
stays watched until its `finished` event, also after the train left the state `landing`, so the end of a run is never
missed between two minutes. `watch-events.json` in the tollman's state folder keeps the run and the keys told
(`job:<run>:<job>`, `merge:<run>`, `done:<run>`; `state`, and `merged`: the landing train's merge job told green, for
minute.py's next train); a quiet pass writes nothing and returns []. Read-only against GitHub.

  watch_events.py [--repo <dir>] [--dry-run]   print the new events (without --dry-run they count as told)
"""

import argparse
import datetime as dt
import os
import sys

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import gh_runs
import job_error
import leavers
import mtm_ci
import mtm_scan
import stack_red
import train_state
import watch

FILE = "watch-events.json"
SCHEMA = 1
KEEP = 200  # keys remembered per run


def target(main: str, rows: list[dict], state: dict) -> dict | None:
    """The run to watch: the landing train's (the run noted for this start is not looked up again), else the last
    one noted that has not finished."""
    train = train_state.standing(rows)
    if train and train.get("state") == "landing":
        started = train.get("started")
        if state.get("train") == train["train"] and state.get("started") == started and not state.get("closed"):
            return state
        url, _ = watch.find(main, train, rows)
        if rid := stack_red.run_id(url):
            return {"run": rid, "url": url, "train": train["train"], "started": started, "seen": [], "closed": False}
    return state if state.get("run") and not state.get("closed") else None


def collect(main: str, tgt: dict) -> list[dict]:
    """The events of the run `tgt` (all of them; `new` drops the told)."""
    rid, url, out = tgt["run"], tgt.get("url"), []
    jobs = gh_runs.jobs([rid], set(), gh_runs.view_jobs(mtm_scan.run_json, main)).get(rid) or []
    red = [j for j in jobs if j.get("name") in mtm_ci.red_jobs(jobs)]
    log = mtm_scan.run(["gh", "run", "view", rid, "--log-failed"], main) if red else None
    for j in red:
        out.append({"key": f"job:{rid}:{j['name']}", "kind": "job-failed",
                    "text": f"job failed: {j['name']}: {job_error.first_error(main, rid, j, log)}"})
    if tgt.get("base"):  # L127: a job past twice its usual time (slow_jobs; the jobs read above, no gh call)
        import slow_jobs
        out += slow_jobs.events(rid, jobs, tgt["base"], dt.datetime.now(dt.timezone.utc))
    row = next((r for r in mtm_ci.runs_of(mtm_scan.run_json, main) if str(r.get("databaseId")) == rid), None)
    if any(j.get("status") == "in_progress" for j in jobs):  # plan 0490 step 25: a red step of a running job
        import step_red
        out += step_red.events(main, rid, url, jobs, row)
    if mtm_ci.merged(jobs):
        name = next(j["name"] for j in jobs if mtm_ci.job_part(j.get("name", "")) in mtm_ci.MERGE_JOBS)
        out.append({"key": f"merge:{rid}", "kind": "merge-green", "text": f"merge job green: {name} ({url})"})
    if row and row.get("status") == "completed":
        out.append({"key": f"done:{rid}", "kind": "finished",
                    "text": f"workflow finished: {row.get('conclusion') or 'unknown'} ({url})"})
    return out


def new(main: str, rows: list[dict], dry: bool = False) -> list[dict]:
    """The events not told before, [{key, kind, text}], each one line; they count as told unless `dry`."""
    state = leavers.read(main, FILE, {})
    tgt = target(main, rows, state)
    if not tgt:
        return []
    if "base" not in tgt:  # once per run: its jobs' medians in the last green runs (L127)
        import slow_jobs
        tgt = {**tgt, "base": slow_jobs.base(main, tgt["run"], dt.datetime.now(dt.timezone.utc))}
    told = set(tgt.get("seen") or [])
    fresh = [e for e in collect(main, tgt) if e["key"] not in told]
    for e in fresh:
        e["text"] = e["text"].replace("\n", " ")
    if not dry and (fresh or tgt is not state):
        done = any(e["kind"] == "finished" for e in fresh)
        leavers.write(main, FILE, {**{k: tgt.get(k) for k in ("run", "url", "train", "started", "base")},
                                   "schema": SCHEMA,
                                   "seen": (list(told) + [e["key"] for e in fresh])[-KEEP:],
                                   "closed": bool(tgt.get("closed")) or done})
    return fresh


def state(main: str) -> dict:
    """The watched run as `watch-events.json` keeps it: {run, url, train, started, base, seen, closed}, or {}."""
    return leavers.read(main, FILE, {})


def merged(main: str, train: dict) -> bool:
    """Whether the merge job of `train`'s current start is told green (plan 0383 step 6: the next train forms)."""
    s = state(main)
    return (s.get("train"), s.get("started")) == (train.get("train"), train.get("started")) and \
        f"merge:{s.get('run')}" in (s.get("seen") or [])


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", default=os.getcwd())
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    home = mtm_scan.main_checkout(a.repo)
    for e in new(home, train_state.lines(home), a.dry_run):
        print(e["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
