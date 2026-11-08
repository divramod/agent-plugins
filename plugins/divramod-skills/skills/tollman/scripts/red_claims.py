#!/usr/bin/env python3
"""One red, one foreman (the user, 2026-11-04: "it would be good, if this triage happens only once. if you do it
multiple times, it could happen, that you send this order to multiple different foreman and then will have doubled
work and merge conflicts and confusion. make this bulletproof").

Every fix order of a car goes through `order` here (orders_cli.py, so also the code's own orders: early_order.py,
run_triage_act.py and run_triage_step_act.py run `tollman.py order`). Under one lock (`orders.lock` in the state
folder) it reads `train.jsonl` fresh, refuses a clash and only then lets orders.order write the line and send the
message, so two writers (the minute pass, the session) never both claim one red.

A red is (run, job, unit). An order's jobs, for this check, are its line's `jobs` plus every staged job name its why
names (`c2-06-python-build-test-linux` → `python-build-test-linux`): the why is logged with the line, so the check
never knows fewer jobs than the message named (the line's `jobs` stay the proof's, fix_proof.py). An order clashes with an earlier order line of the same run to ANOTHER field that names one of its
jobs, unless the new order names its own units (`--unit <test or file>`) and none of them is a unit of that line or
appears in its why: one job may hold several culprits (three different failing tests in one bats job), each told
once. The same field is no clash: orders.order adds the job to its open order (`also`) or says it stands.

The refusal names the earlier order and its field; the triage then either takes it as covered or names the distinct
unit. `red_orders.py check` shows per red job whom it went to.
"""

import fcntl
import re
from contextlib import contextmanager

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import orders
import stack_red
import train_state

LOCK = "orders.lock"
# In free text (an order's why) a stage prefix alone would also find a lane id (`c1-hz01-host-a`): a job with a place,
# or one of the one-job lanes' jobs without one (plan 0728 D40, `a1-ci-route`).
ONE_JOB_LANES = r"ci-route|ci-changes|publish-ios|publish-android|ci-cache-clean-[a-z-]*[a-z]"
STAGED = re.compile(rf"\b[a-z][1-9]-(?:\d\d-[a-z0-9][a-z0-9-]*[a-z0-9]|(?:{ONE_JOB_LANES})(?![a-z0-9-]))")


def rid_of(url) -> str:
    return str(url or "").rstrip("/").rsplit("/", 1)[-1]


def jobs_of(jobs, why: str) -> list[str]:
    """The bare jobs an order names: its `jobs` and the staged job names in its why, in order, once."""
    named = [stack_red.bare(m) for m in STAGED.findall(str(why or "").lower())]
    return list(dict.fromkeys([stack_red.bare(j) for j in jobs or []] + named))


def clash(rows: list[dict], field: str, run: str | None, jobs: list[str], units: list[str]) -> str | None:
    """Why an order to `field` for `jobs` (with `units`) of `run` would tell a second foreman, or None."""
    rid = rid_of(run)
    if not rid or field == orders.MAIN:
        return None
    for e in rows:
        if e.get("kind") != "order" or rid_of(e.get("run")) != rid or e.get("field") == field:
            continue
        shared = [j for j in jobs if j in jobs_of(e.get("jobs"), e.get("why"))]
        if not shared:
            continue
        theirs, why = set(e.get("units") or []), str(e.get("why") or "")
        same = [u for u in units if u in theirs or u in why]
        if not units or same:
            what = f"unit {same[0]}" if same else "it (no --unit names a different failing test)"
            return (f"no fix order: {', '.join(shared)} of run {rid} went to {e.get('field')} already "
                    f"({e.get('also') or e.get('id')}), {what}: one red, one foreman. A different failing test of the "
                    f"same job: name it with --unit <test or file>; else it is covered (red_orders.py check)")
    return None


@contextmanager
def locked(main: str):
    folder = train_state.folder(main)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / LOCK).open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def order(top: str, field: str, why: str, run: str | None, panes: dict, now=None, smuggle: bool = False,
          post: str | None = None, jobs: list[str] | None = None,
          units: list[str] | None = None) -> tuple[int, str, list[dict]]:
    """orders.order behind the clash check, under the lock (see the module doc)."""
    main = mtm_scan.main_checkout(top)
    units = list(dict.fromkeys(u.strip() for u in units or [] if u and u.strip()))
    with locked(main):
        rows = train_state.lines(main)
        train = train_state.standing(rows) or {}
        all_jobs = jobs_of(jobs, why)
        if why_not := clash(rows, field, run or train.get("run") or train.get("land_run"), all_jobs, units):
            return 1, why_not, []
        return orders.order(top, field, why, run, panes, now, smuggle=smuggle, post=post, jobs=jobs,
                            units=units or None)
