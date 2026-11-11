"""The pretest of a train (hal2 plan 0349 step 28, D75), the engine's side of pretest.py: `engine.py land` calls
`before_landing` first, in the carrier's field on the train's merged candidate.

Once per candidate tree: a pretest line of the train state (`pretest`: `seconds`, `result`, `jobs`, `why`, `tree`,
the tree of the HEAD it tested) and its jobs' output in `train-pretest.log` (rewritten). A train whose last pretest
was green, skipped or none on the tree HEAD has now is not pretested again (the restart of an interrupted landing
adopts its run); a fix merged after it, or the barn merged in, is a new tree and is pretested again (plan 0522: train
32 was pretested once and landed eight fixes untested). After a red one the session's `retry` pretests again (a red
is never cached), its `retry --skip-pretest` writes a `skipped` line with the tree in its place (a red that is the
Mac's, not a car's: engine_car.retry). Incomplete (the budget cut a job, the gate did not answer: plan 0522 D7): no
landing starts, one JSON line `{"status": "pretest_incomplete", "message": ...}`; trains.settle starts the landing
again (its markers keep what was green) up to WAITS times in a row, then wakes the session as a red train. Before
that, an incomplete pretest, or one skipped because it broke, is run once more with twice its budget (plan 0623 D3,
`retry_worthy`; the line says `retried`): a green retry blocks nothing, a second skip pushes as before. Red: one
JSON line on stdout, which the landing's log keeps as its result (train_state.result), and no landing starts; every
red job is named, each with its first error line and its suspects (plan 0522 D14: one wake, one fix order per car
for all its reds):

  {"status": "pretest_red", "red": [{"name": <job>, "log": <train-pretest.log>, "line": <its first error line>,
   "suspects": [<field>|"yard"]}, ...], "suspects": [<every red's suspects, in car order>],
   "message": "pretest: <job> red (car <field>), <job> red (cars <field>, <field>)"}

trains.settle takes that to the red path: the train waits, frozen (plan 0360 D3), for its fix or the session's
`retry`. A red job's suspects are the cars whose own range selects it (`gate plan` over the barn's merge base .. the
car's head, once per car for all reds; the yard's car: its commit's parent .. its commit), within BLAME_SECONDS; none
selects it, or the gate does not answer in time: every car. A pretest that breaks before a red is known is `skipped`
and never holds a train; once a red is known it ends as pretest_red, whatever fails after. SIGTERM to the landing's
process ends the pretest's jobs with it.
"""

import contextlib
import json
import signal
import subprocess
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import local_load
import mtm_scan
import pretest
import train_state
from tick import default_ref

LOG = "train-pretest.log"
STATUS = "pretest_red"
INCOMPLETE = "pretest_incomplete"  # trains.py's PRETEST_WAIT
RETRY_SCALE = 2  # the one retry of an incomplete or broken pretest runs with twice the gate wait and job budget
WAITS = 3  # incomplete pretests in a row that start the landing again by code (trains.settle), then the wake
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
    tree = pretest.git(top, "rev-parse", "HEAD^{tree}")
    if not train or not due(train, tree):
        return False
    state = train_state.folder(main)
    with sigterm_exits(), local_load.Phase() as phase:  # what the pretest costs the machine (plan 0472 step 4)
        r, progress = attempt(top, state)
        retried = retry_worthy(r)
        if retried:  # plan 0623 D3: once more with twice the budget before the train pushes without it or waits
            print(f"pretest: {r['result']} in {r['seconds']} s ({r['why']}): once more with twice the budget",
                  flush=True)
            first, (r, progress) = r, attempt(top, state, RETRY_SCALE)
            r = {**r, "seconds": round(first["seconds"] + r["seconds"], 1)}
    with contextlib.suppress(OSError):
        train_state.append(main, "pretest", Path(top).name, train=train["train"], seconds=r["seconds"],
                           result=r["result"], jobs=r["jobs"], why=r["why"] or None, local=phase.record(),
                           tree=tree or None, retried=True if retried else None)
    print(f"pretest: {r['result']} in {r['seconds']} s" + (f" ({r['why']})" if r["why"] else ""), flush=True)
    if r["result"] == "incomplete":
        print(json.dumps({"status": INCOMPLETE, "message": f"pretest incomplete: {r['why']}"[:300]}), flush=True)
        return True
    if r["result"] != "red":
        return False
    jobs = [j["job"] for j in r["jobs"] if j["result"] == "red"] or [progress.get("red", "?")]
    rows = []
    with contextlib.suppress(OSError):
        rows = train_state.lines(main)
    named = blame_all(top, train, jobs, r.get("base") or default_ref(top), yard_commit(rows, train["train"]))
    every = [f for f in [c["field"] for c in train.get("cars", [])] + [train_state.YARD]
             if any(f in s for s in named.values())]
    errors = r.get("errors") or {}
    red = [{"name": j, "log": str(state / LOG), **({"line": errors[j]} if errors.get(j) else {}), "suspects": named[j]}
           for j in jobs]
    told = ", ".join(f"{j} red (car{'s' * (len(named[j]) > 1)} {', '.join(named[j])})" for j in jobs)
    print(json.dumps({"status": STATUS, "red": red, "suspects": every, "message": f"pretest: {told}"[:600]}),
          flush=True)
    return True


def attempt(top: str, state: Path, scale: float = 1.0) -> tuple[dict, dict]:
    """One pretest run (its budget times `scale`) and its progress; a broken one is no red train, unless a red was
    already known."""
    progress: dict = {}
    try:
        return pretest.pretest(top, state, default_ref(top), state / LOG, progress=progress, scale=scale), progress
    except Exception as e:  # noqa: BLE001
        return {"result": "red" if progress.get("red") else "skipped", "seconds": 0, "jobs": [],
                "why": f"the pretest broke: {e}"[:300]}, progress


def retry_worthy(r: dict) -> bool:
    """Whether a pretest is run once more: it ended incomplete (the gate did not answer, the budget cut a job) or
    skipped because it broke. A skip with another reason (no build, a job changed files, the Mac's tool) is final."""
    return r["result"] == "incomplete" or (r["result"] == "skipped" and str(r["why"]).startswith("the pretest broke"))


def due(train: dict, tree: str) -> bool:
    """Whether the train must be pretested: never yet, its last one red or incomplete, or on another tree (a line
    without a tree, from before plan 0522, counts as another)."""
    last = train.get("pretest")
    return last not in ("green", "skipped", "none") or not tree or train.get("pretest_tree") != tree


def yard_commit(rows: list[dict], name: str) -> str | None:
    """The commit the yard's car made in the carrier for the train `name`, if it rode; `<merged>..<last>` when the
    yard's commits rode as a merge first (plan 0789 D2): the range then starts before that merge."""
    e = next((e for e in rows if e["kind"] == "yard" and e.get("train") == name), {})
    last = e.get("commit") or e.get("merged")
    return f"{e['merged']}..{last}" if last and e.get("merged") else last


def blame(top: str, train: dict, job: str, base: str, yard: str | None = None) -> list[str]:
    """The cars whose own range selects `job` (blame_all's, for one job)."""
    return blame_all(top, train, [job], base, yard)[job]


def blame_all(top: str, train: dict, jobs: list[str], base: str, yard: str | None = None) -> dict[str, list[str]]:
    """Each of `jobs` with the cars whose own range selects it; every car (and `yard`) for a job none selects, and
    for all when the gate did not answer for every car within BLAME_SECONDS. One `gate plan` per car. Never raises."""
    every = [c["field"] for c in train.get("cars", [])] + ([train_state.YARD] if yard else [])
    try:
        gate, deadline, picked = Path(top) / pretest.GATE, time.monotonic() + BLAME_SECONDS, {}
        ranges = [(c["field"], pretest.git(top, "merge-base", base, c["head"]) or base, c["head"])
                  for c in train.get("cars", [])]
        first, _, yard = (yard or "").rpartition("..")  # yard_commit's range: its start's parent, else the commit's
        ranges += [(train_state.YARD, pretest.git(top, "rev-parse", f"{first or yard}^") or base, yard)] if yard else []
        for field, start, head in ranges:
            left = deadline - time.monotonic()
            if left <= 0:
                return {j: every for j in jobs}
            picked[field] = pretest.plan(top, gate, start, head, left)
        return {j: [f for f, chosen in picked.items() if j in chosen] or every for j in jobs}
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError):
        return {j: every for j in jobs}
