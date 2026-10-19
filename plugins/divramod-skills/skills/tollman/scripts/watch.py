#!/usr/bin/env python3
"""The watch on a train's land run while its landing runs (hal2 plan 0360 step 5, D4, D32): what `trains.plan`
returns each round for a live landing, which it left alone before.

1. The run: nothing records its id while the landing's process lives (hal2-cli-git's `merge-to-main --json` prints
   one JSON line at its end only, ci_land.rs), so it is found by code: the newest run of a landing workflow
   (mtm_ci.runs_of) on the train's own branch `land/<land_ref>` (its `started` line's, train_branch.py, plan 0383;
   `land/<carrier>` for a train started before) created at or after the train's last `started` (a retry's fresh
   commit gives a new run, and its new start leaves the old run behind). Once found it is noted as a `run` line of
   train.jsonl (`watch.py run <url>`, an action), and later rounds read it from there (train_state.land_run).
   After a smuggle's pause (pause.py) the run is looked for again among those created since the pause began.
2. Its jobs (`gh run view <id> --json jobs`, the round's shared fetch, gh_runs); the red ones by mtm_ci.red_jobs
   (fail-fast cancels, ship, build and stop jobs left out). At the first red job: triage (triage.py); a runner fault
   wakes nobody (trains.settle retries it once the landing has ended red), nor does a pause's cancel or a smuggle's
   red (settle orders the smuggling field, plan 0360 step 18); a car's red whose triage names exactly one car is
   that car's fix order by code while the run runs (early_order.py, plan 0383 step 5, D5), the barn's red or an
   unclear culprit wakes the session once, keyed `train-red:<run id>` (tick.fresh drops the same key in later
   rounds and settle's own wake). A red after the merge job is green is post_merge.py's (plan 0383 step 6): its
   car's fix order rides the next train.

  watch.py run <url> [--repo <dir>]   note the standing train's land run (the action of step 1)
"""

import argparse
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import gh_runs
import mtm_ci
import mtm_scan
import post_merge
import stack_red
import train_branch
import train_state
from tick import act

HERE = Path(__file__).resolve()


def find(main: str, train: dict | None, rows: list[dict]) -> tuple[str | None, bool]:
    """(the land run's address of the train's current start, whether it is new: not noted in train.jsonl yet)."""
    if not train or not train.get("started"):
        return None, False
    if cached := train.get("land_run"):  # the train as the round sees it (a resumed one has none)
        return cached, False
    since = mtm_ci.started({"createdAt": train.get("since") or train["started"]})  # after a pause: the newer run
    branch = train_branch.land(train)
    hit = next((r for r in mtm_ci.runs_of(mtm_scan.run_json, main)
                if r.get("headBranch") == branch and mtm_ci.started(r) >= since), None)
    return (hit.get("url") or str(hit.get("databaseId")), True) if hit else (None, False)


def record(top: str, name: str, url: str, rid: str) -> dict:
    """The action that notes the run (`watch.py run`); a failed one wakes the session once."""
    argv = [sys.executable, str(HERE), "run", url, "--repo", top]
    key = f"train-run:{name}:{rid}"
    stuck = act("trains", "train-stuck", "wake", key=f"stuck:{key}",
                text=f"the land run {url} was not noted: run `{' '.join(argv[1:])}` to see why")
    return act("trains", "train-run", "run", "-", key=key, argv=argv, text=f"train {name} lands in {url}",
               on_fail=[stuck])


def actions(top: str, main: str, train: dict, rows: list[dict], tickets=()) -> list[dict]:
    """The round's actions for the live landing of `train` (see the module doc)."""
    url, new = find(main, train, rows)
    rid = stack_red.run_id(url)
    if not rid:
        return []
    out = [record(top, train["train"], url, rid)] if new else []
    jobs = gh_runs.jobs([rid], set(), gh_runs.view_jobs(mtm_scan.run_json, main)).get(rid) or []
    return out + post_merge.red(top, main, train, url, rid, jobs, tickets)  # a red job: order or wake


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb", required=True)
    noted = sub.add_parser("run")
    noted.add_argument("url")
    noted.add_argument("--repo", default=".")
    a = p.parse_args(argv)
    home = mtm_scan.main_checkout(a.repo)
    train = train_state.standing(train_state.lines(home))
    if not train or train["state"] != "landing":
        print("no landing train stands: nothing noted")
        return 0
    train_state.append(home, "run", train["carrier"], train=train["train"], run=a.url)
    print(f"train {train['train']} lands in {a.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
