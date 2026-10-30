#!/usr/bin/env python3
"""A dry baseline of the minute pass (hal2 plan 0480 step 01.03, D1): `n` passes of what a quiet pass reads, timed as
pass_timing times the real one.

Each pass is the queue read (`hal2-cli-git worktree queue --json`) plus `minute.events(dry=True)` (the watch's events and
`ci_health.check(dry=True)`: the runners, the live runs' queued jobs) inside a gh_runs round; it plans only, writes no
state and sends, cancels, reruns or merges nothing: GitHub is read-only. The state root is a scratch folder (FARMER_DIR,
made here when unset), so the live tollman's files are neither read nor written and no train stands (a quiet pass).
It leaves out `leavers.check` (it may act) and the interpreter's start and imports, which the real pass's wall includes.

  pass_baseline.py [--passes 10] [--repo <dir>] [--json]   print each pass's record, then the medians
"""

import argparse
import json
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

if not os.environ.get("FARMER_DIR"):
    os.environ["FARMER_DIR"] = tempfile.mkdtemp(prefix="pass-baseline-")  # before roles.py reads it
    atexit.register(shutil.rmtree, os.environ["FARMER_DIR"], True)  # leaves nothing behind

import farmer_frame  # noqa: F401,E402  (the farmer skill's frame on the import path)
import gh_runs  # noqa: E402
import minute  # noqa: E402
import mtm_scan  # noqa: E402
import pass_timing  # noqa: E402
import trains  # noqa: E402


def one(top: str, main: str) -> dict:
    """One dry pass's record."""
    pass_timing.begin()
    with gh_runs.round(None):
        doc = mtm_scan.run_json(trains.QUEUE, main) or {}
        minute.events(top, main, True, doc)
    rec = pass_timing.record()
    pass_timing.abandon()
    return rec


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--passes", type=int, default=10)
    p.add_argument("--repo", default=".")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    top = minute.tick.git(a.repo, "rev-parse", "--show-toplevel")
    main_dir = str(mtm_scan.main_checkout(top))
    rows = [one(top, main_dir) for _ in range(a.passes)]
    s = pass_timing.summary(rows)
    if a.json:
        print(json.dumps({"passes": rows, "summary": s}))
        return 0
    for r in rows:
        print(json.dumps(r))
    print("median " + ", ".join(f"{k} {s[k]['median']:g}" for k in pass_timing.FIELDS) + f" over {s['passes']} passes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
