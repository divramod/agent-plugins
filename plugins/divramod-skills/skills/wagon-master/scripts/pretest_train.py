"""The pretest of a train (hal2 plan 0349 step 28, D75), the engine's side of pretest.py: `engine.py land` calls
`before_landing` first, in the carrier's field on the train's merged candidate.

Once per train: a pretest line of the train state (`pretest`: `seconds`, `result`, `jobs`, `why`) and its jobs'
output in `train-pretest.log` (rewritten). A train whose last pretest was not red is not pretested again (the
restart of an interrupted landing adopts its run); after a red one the session's `retry` pretests again (a red is
never cached), its `retry --skip-pretest` writes a `skipped` line in its place (a red that is the Mac's, not a
car's: engine.retry). Red: one JSON line on stdout, which the landing's log keeps as its result
(train_state.result), and no landing starts:

  {"status": "pretest_red", "red": [{"name": <job>, "log": <train-pretest.log>}], "suspects": [<field>|"yard"],
   "message": "pretest: <job> red, car <field>"}

trains.settle takes that to the red path: the train waits for the session's `unhitch` or `retry`. The suspects are
the cars whose own range selects the red job (`gate plan` over the barn's merge base .. the car's head; the yard's
car: its commit's parent .. its commit), within BLAME_SECONDS; none selects it, or the gate does not answer in time:
every car. A pretest that breaks before a red is known is `skipped` and never holds a train; once a red is known
it ends as pretest_red, whatever fails after. SIGTERM to the landing's process ends the pretest's jobs with it.
"""

import contextlib
import json
import signal
import subprocess
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import pretest
import train_state
from tick import default_ref

LOG = "train-pretest.log"
STATUS = "pretest_red"
BLAME_SECONDS = 60


@contextlib.contextmanager
def sigterm_exits():
    """SIGTERM raises SystemExit while the pretest runs, so its jobs are stopped on the way out (run_jobs' finally)."""
    def leave(sig, _frame):
        raise SystemExit(128 + sig)

    old = signal.signal(signal.SIGTERM, leave)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, old)


def before_landing(top: str) -> bool:
    """The pretest of the train that stands in `top` (the module doc): True when it is red and the landing must not
    start."""
    main = mtm_scan.main_checkout(top)
    train = train_state.standing(train_state.lines(main))
    if not train or train.get("pretest") not in (None, "red"):
        return False
    state, progress = train_state.folder(main), {}
    with sigterm_exits():
        try:
            r = pretest.pretest(top, state, default_ref(top), state / LOG, progress=progress)
        except Exception as e:  # noqa: BLE001  (a broken pretest is no red train, unless a red was already known)
            r = {"result": "red" if progress.get("red") else "skipped", "seconds": 0, "jobs": [],
                 "why": f"the pretest broke: {e}"[:300]}
    with contextlib.suppress(OSError):
        train_state.append(main, "pretest", Path(top).name, train=train["train"], seconds=r["seconds"],
                           result=r["result"], jobs=r["jobs"], why=r["why"] or None)
    print(f"pretest: {r['result']} in {r['seconds']} s" + (f" ({r['why']})" if r["why"] else ""), flush=True)
    if r["result"] != "red":
        return False
    job = next((j["job"] for j in r["jobs"] if j["result"] == "red"), None) or progress.get("red", "?")
    rows = []
    with contextlib.suppress(OSError):
        rows = train_state.lines(main)
    suspects = blame(top, train, job, r.get("base") or default_ref(top), yard_commit(rows, train["train"]))
    print(json.dumps({"status": STATUS, "red": [{"name": job, "log": str(state / LOG)}], "suspects": suspects,
                      "message": f"pretest: {job} red, car{'s' * (len(suspects) > 1)} {', '.join(suspects)}"}),
          flush=True)
    return True


def yard_commit(rows: list[dict], name: str) -> str | None:
    """The commit the yard's car made in the carrier for the train `name`, if it rode."""
    return next((e.get("commit") for e in rows if e["kind"] == "yard" and e.get("train") == name), None)


def blame(top: str, train: dict, job: str, base: str, yard: str | None = None) -> list[str]:
    """The cars whose own range selects `job`; every car (and `yard`) when none does, or when the gate did not
    answer for every car within BLAME_SECONDS. Never raises."""
    every = [c["field"] for c in train.get("cars", [])] + ([train_state.YARD] if yard else [])
    try:
        gate, deadline, named = Path(top) / pretest.GATE, time.monotonic() + BLAME_SECONDS, []
        ranges = [(c["field"], pretest.git(top, "merge-base", base, c["head"]) or base, c["head"])
                  for c in train.get("cars", [])]
        ranges += [(train_state.YARD, pretest.git(top, "rev-parse", f"{yard}^") or base, yard)] if yard else []
        for field, start, head in ranges:
            left = deadline - time.monotonic()
            if left <= 0:
                return every
            if job in pretest.plan(top, gate, start, head, left):
                named.append(field)
        return named or every
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError):
        return every
