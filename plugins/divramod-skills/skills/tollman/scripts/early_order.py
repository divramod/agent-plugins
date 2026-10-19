"""The early fix order (hal2 plan 0383 step 5, D5, L32, L35): a red job of a train's live land run is triaged at once,
and when the triage names exactly one car the code orders that car's foreman while the run still runs, no wake.

- the hooks: the round (watch.actions, each round while the train lands) and the watch duty (minute.py: the minute
  pass and the round's `duty:watch`, on a fresh `job failed` event of watch_events.py); the same keys, so a tick
  and the next never act twice (tick.fresh), and `once` keeps two handlers of one round from it
- the triage: triage.classify; `runner`, `none` and `smuggled` need nobody here (trains.settle and train_red act at
  the run's end); `main` and a `car` red whose culprit is unclear wake the session, keyed `train-red:<run id>`
- the culprit (`culprit`): the only car of a train without the yard's car, else the one car (the yard counts as one)
  whose files the red names: a path in the failed log's tail, or a file's stem in a failing test (smuggled.touched's
  rule); none or two or more: unclear. A red after the run's merge job is green is no early order: the train is in
  the barn then, post_merge.py orders it into the next train (plan 0383 step 6)
- the order: `tollman.py order <car> --why "<job>: <first error line>" --run <url>` (orders.py: the train stays
  `landing`, the foreman fixes on `<NN>-train-fix` from `origin/<carrier>` and answers `done fixed <sha>`), keyed
  `early-order:<run id>`; a failed order wakes the session as an unclear one does. While an early order stands the
  run is not triaged again; its `fixed` waits for the run's end (L34)
"""

import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import job_error
import mtm_ci
import smuggled
import train_red
import train_state
import triage
from tick import act

CLI = Path(__file__).with_name("tollman.py")
KINDS = ("early-order", "train-red", "post-order")  # the actions `once` keeps to one per round
QUIET = ("runner", "none", "smuggled")  # reds the run's end settles (train_red.py)


def culprit(train: dict, verdict: dict) -> str | None:
    """The one car the `car` verdict names, or None (see the module doc)."""
    if verdict["kind"] != "car":
        return None
    e = verdict["evidence"]
    rows = [{"slot": c["field"], "files": c.get("files") or []} for c in e.get("cars") or []]
    if train.get("yard"):
        rows.append({"slot": train_state.YARD, "files": [f["path"] for f in train["yard"]]})
    named = rows if len(rows) == 1 else [r for r in rows if smuggled.touched([r], e.get("tail"), e.get("tests") or [])]
    return named[0]["slot"] if len(named) == 1 and named[0]["slot"] != train_state.YARD else None


def why_of(main: str, rid: str, red: list[dict], tail: str | None) -> str:
    """`<job>: <its first error line>` for the run's first red job; `tail`: the triage's failed log."""
    return f"{red[0].get('name')}: {job_error.first_error(main, rid, red[0], tail)}" if red else "a red job"


def actions(top: str, main: str, train: dict, url: str, rid: str, jobs: list[dict], tickets=(),
            why: str | None = None) -> list[dict]:
    """The round's or the pass's action for the live run `rid` whose jobs are `jobs`: the order, a wake, or none."""
    if any(o.get("early") for o in train.get("orders") or []):
        return []  # ordered already: the run's end makes the train `fixing`
    names = mtm_ci.red_jobs(jobs)
    red = [j for j in jobs if j.get("name") in names]
    if not red:
        return []
    verdict = triage.classify(*triage.gather(main, train, url, names, jobs, list(tickets)))
    if verdict["kind"] in QUIET:
        return []
    wake = act("trains", "train-red", "wake", key=f"train-red:{rid}", evidence={**verdict, "train": train},
               text=train_red.text(verdict, train, "is red while it lands", ", ".join(names), url))
    field = None if mtm_ci.merged(jobs) else culprit(train, verdict)  # after the merge: post_merge.red's
    if not field:
        return [wake]
    why = (why or why_of(main, rid, red, verdict["evidence"].get("tail")))[:300]
    argv = [sys.executable, str(CLI), "order", field, "--why", why, "--run", url, "--repo", top]
    return [act("trains", "early-order", "run", field, key=f"early-order:{rid}", argv=argv, on_fail=[wake],
                text=f"train {train['train']}: fix order to {field} while its run runs ({why[:120]})")]


def once(ctx: dict, planned: list[dict]) -> list[dict]:
    """`planned` without the early orders and red wakes another handler of this round planned already."""
    seen = ctx.setdefault("early_keys", set())
    out = [a for a in planned if a["kind"] not in KINDS or a.get("key") not in seen]
    seen.update(a.get("key") for a in out if a["kind"] in KINDS)
    return out
