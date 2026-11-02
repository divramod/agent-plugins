"""The unchanged-head guard (hal2 plan 0560 step 3, D5; tollman learning L200): a red train is never landed again on
the head of its last red run. `engine.land` asks `refuses` right before the landing, after the wait for the run before
and the post-merge fixes (next_train.py), the last point before every push (a restart, a retry, a resume):

1. the carrier's HEAD equals the head of the train's last push (train_state's `push` line, kept across starts) and
   that push is red: a `red` line named its head, or its land run ended red on GitHub (L200: the landing died, no
   `red` line, the run failed): refused. One line `tollman: refused: ...` and the landing's result as a JSON line
   (`status` `refused`, `run` the red run, `message` the line), so the round records the red at once and the triage
   reads that run (train_red.py), never a restart that would only be refused again; exit 1.
2. else the `push` line (`head`: the HEAD it lands) and exit 0: the landing goes on.

A retry's empty commit (`engine.fresh`, a flaky gate) and a fix's merge make a new head on purpose: they land. A
HEAD git cannot read, or no standing train: no guard, no line.
"""

import json
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_ci
import mtm_scan
import stack_red
import train_state
from carrier import git

RED = ("failure", "timed_out", "startup_failure")  # a run that ended so is red; `cancelled` (a pause) is not
LINE = "tollman: refused: train {n}'s candidate {head} is the head of its last red run {run}; waiting for a fix"


def run_red(main: str, run: str | None) -> bool:
    """The land run `run` ended red on GitHub (no answer: not known red)."""
    rid = stack_red.run_id(run)
    return bool(rid) and any(str(r.get("databaseId")) == rid and r.get("status") == "completed"
                             and r.get("conclusion") in RED for r in mtm_ci.runs_of(mtm_scan.run_json, main))


def refuses(top: str) -> int:
    """1 (printed) when the carrier `top`'s HEAD is the head of the train's last red run, else 0 (the `push` line)."""
    main = mtm_scan.main_checkout(top)
    train = train_state.standing(train_state.lines(main))
    if not train:
        return 0
    code, head = git(top, "rev-parse", "HEAD")
    if code or not head:
        return 0
    last = train.get("push") or {}
    if head == last.get("head") and (last.get("red") or run_red(main, last.get("run"))):
        line = LINE.format(n=train.get("number") or train["train"], head=head[:12], run=last.get("run") or "none")
        print(line, flush=True)
        print(json.dumps({"status": "refused", "run": last.get("run"), "message": line}), flush=True)
        return 1
    train_state.append(main, "push", Path(top).name, train=train["train"], head=head)
    return 0
