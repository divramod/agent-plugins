#!/usr/bin/env python3
"""The push waits for the post-merge reds' fix cars (hal2 plan 0490 step 21; D21, D22, D23, D9; the plan's
open-train-brief.md, point 2 and its Amendment): run by next_train.before_push in the landing's own process, after
next_train.wait (the run before has concluded as a whole, D23) and before the push.

The run before is the land run of the train landed last before this one formed (its `landed` line). Concluded
`success`: no red, no wait, no read of the triage (D9). Else its triage (run_triage_wire.py, beside the next train)
keeps `reds` in run-triage.json: one compact verdict per red unit (`compact`). Each round, one pass over them: the
answered post-merge fixes merged first (next_train.merge_posts), then each red is

- a named reason: the triage's quiet kinds (`runner`, `flake`, `needs-red`: not ours to fix), or the session's
  `reason` (this script's CLI, the word after a wake), keyed by the red or `*` for every red of the run;
- or has its fix car: a `fixed` line of this train for an order of that run (the triage's or post_merge's) to the red's
  owner or naming its job (orders.take merged it), or a car of the train (formed or joined) whose commits after the
  red run's creation touch the red's files (run_triage_dedup's own rule for a hitched wagon), or, for a red that
  names no file, any such commit of a car of its owner;
- else it holds the push. While one holds, the round ends with the open train's join round (open_train.take: a fix
  hitched as a wagon joins) and a sleep; the next round looks again. No triage written yet (or a failed one): every
  red is unknown and holds.

A timeout never pushes (D22): TIMEOUT seconds after the wait began (None: the run before's wall time, its creation to
the moment the wait saw it concluded; FALLBACK when that is not known) one wake goes to the tollman (`push-waits`,
kept with the run's triage and offered by run_triage_wire.pending: the reds still waiting, their owners and orders,
and the `reason` command) and the wait goes on until each red has its fix car or a reason.

  fix_wait.py reason --repo <field> --run <url|id> [--red <key>] --why <text>   a named reason (no --red: every red)
"""

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_ci
import mtm_scan
import run_triage_dedup as dedup
import run_triage_wire as wire
import train_state
from tick import act

TIMEOUT = None  # seconds the push waits for the fixes before the wake; None: the run before's wall time
FALLBACK = 3600  # the wall time when the run's creation is not known
QUIET = ("needs-red", "runner", "flake")  # the triage's kinds that are not ours to fix (run_triage.QUIET)
ALL = "*"  # a reason for every red of the run
POLL = 30  # seconds between the rounds (next_train.POLL)
CLI = Path(__file__).resolve()


def compact(verdicts: list[dict], at: str | None) -> list[dict]:
    """The triage's verdicts as the wait reads them (kept in run-triage.json as `reds`)."""
    out = []
    for v in verdicts:
        e, (exact, prefixes) = v.get("evidence") or {}, dedup.red_files(v)
        out.append({"key": v["key"], "kind": v["kind"], "job": e.get("job"), "unit": e.get("unit"),
                    "owner": v.get("owner"), "run": e.get("run"), "at": at, "files": sorted(exact),
                    "prefixes": list(prefixes)})
    return out


def rid_of(url) -> str:
    return str(url or "").rstrip("/").rsplit("/", 1)[-1]


def run_before(rows: list[dict], name: str) -> str | None:
    """The land run of the train landed last before the train `name` formed."""
    last = None
    for e in rows:
        if e.get("kind") == "landed":
            last = e.get("run")
        elif e.get("kind") == "formed" and e.get("train") == name:
            return last
    return None


def fixed_orders(rows: list[dict], name: str) -> list[dict]:
    """The orders whose fix a `fixed` line merged into the train `name`: their `order` lines."""
    ids = {e.get("id") for e in rows if e.get("kind") == "fixed" and e.get("train") == name}
    return [e for e in rows if e.get("kind") == "order" and e.get("id") in ids]


def car_fix(red: dict, cars: list[dict], main: str, read, seen: dict) -> str | None:
    """The car whose commits after the red run's creation fix the red (the module doc), or None."""
    exact, prefixes = set(red.get("files") or []), tuple(red.get("prefixes") or [])
    for car in cars:
        mine = car.get("field") == red.get("owner")
        if not (exact or prefixes or mine) or not car.get("head"):
            continue
        k = (car["head"], red.get("at"))
        if k not in seen:  # a head's commits never change: read once per wait
            seen[k] = read(main, {"field": car.get("field"), "head": car["head"]}, red.get("at"))
        files = seen[k]
        if (exact or prefixes) and dedup.hits(files, exact, prefixes) or not (exact or prefixes) and files:
            return f"car {car['field']} ({car['head'][:12]})"
    return None


def why_held(red: dict, train: dict, fixed: list[dict], reasons: dict, main: str, read, seen: dict) -> str | None:
    """None when the red holds the push, else why it does not (a named reason or its fix car)."""
    if red["kind"] in QUIET:
        return f"{red['kind']}: not ours"
    if why := reasons.get(red["key"]) or reasons.get(ALL):
        return f"reason: {why}"
    for o in fixed:
        if rid_of(o.get("run")) == rid_of(red.get("run")) and (
                o.get("field") == red.get("owner") or (red.get("job") and red["job"] in str(o.get("why") or ""))):
            return f"fix order {o.get('id')} of {o.get('field')} merged"
    return car_fix(red, train.get("cars") or [], main, read, seen)


def holding(main: str, train: dict, rows: list[dict], entry: dict, read, seen: dict) -> list[dict] | None:
    """One pass over the triage's result: the reds that hold the push; None while the triage has not written its
    reds (or failed): every red unknown."""
    reasons = entry.get("reasons") or {}
    if not entry.get("at") or entry.get("error") or not isinstance(entry.get("reds"), list):
        return None if ALL not in reasons else []
    fixed = fixed_orders(rows, train["train"])
    return [r for r in entry["reds"] if not why_held(r, train, fixed, reasons, main, read, seen)]


def entry_of(main: str, rid: str) -> dict:
    return next((r for r in wire.state(main)["runs"] if r.get("run") == rid), {})


def concluded(main: str, rid: str) -> dict | None:
    """The run's row in the landing workflow's runs list, or None."""
    return next((r for r in mtm_ci.runs_of(mtm_scan.run_json, main) if str(r.get("databaseId")) == rid), None)


def wall(row: dict, now: dt.datetime) -> float:
    """The run's wall time: its creation to `now` (the moment the wait saw it concluded); FALLBACK when not known."""
    try:
        made = dt.datetime.fromisoformat(str(row.get("createdAt")).replace("Z", "+00:00"))
    except ValueError:
        return FALLBACK
    seconds = (now - made).total_seconds()
    return seconds if seconds > 0 else FALLBACK


def says(left: list[dict] | None, url: str) -> str:
    if left is None:
        return f"the push waits for the triage of run {rid_of(url)} (its red jobs are not known yet)"
    return (f"the push waits for the fix cars of run {rid_of(url)}'s reds: " +
            ", ".join(f"{r.get('unit') or r.get('job')} ({r['kind']}, {r.get('owner') or 'no owner'})" for r in left))


def wake(main: str, train: dict, url: str, left: list[dict] | None, seconds: float, now: dt.datetime) -> None:
    """The timeout's one wake, kept with the run's triage (run_triage_wire.pending offers it)."""
    rid = rid_of(url)
    orders = {o.get("field"): o.get("id") for o in train.get("post") or [] if rid_of(o.get("run")) == rid}
    reds = "the triage's reds are not known (not written or failed)" if left is None else "; ".join(
        f"{r.get('unit') or r.get('job')} ({r['kind']}): owner {r.get('owner') or 'none'}, " +
        (f"fix order {orders[r.get('owner')]}" if orders.get(r.get("owner")) else "no open fix order") for r in left)
    text = (f"train {train['train']} has not pushed: {int(seconds)} s after run {url} concluded its reds still wait "
            f"for their fix cars (D22: never a push without them): {reds}. Get each fix hitched or its order answered, "
            f"or name why it is not ours: `python3 {CLI} reason --repo <field> --run {rid} [--red <key>] --why <text>`")
    action = act("trains", "push-waits", "wake", key=f"push-waits:{rid}:{train['train']}", text=text,
                 evidence={"run": url, "train": train["train"], "reds": left})
    wire.update(main, rid, lambda e: e.update(push={"at": now.isoformat(timespec="seconds"), "action": action}))


def fixes(main: str, name: str, merge, join, sleep=time.sleep, clock=time.monotonic,
          now=lambda: dt.datetime.now(dt.timezone.utc), read=dedup.touched) -> list[str]:
    """The wait (the module doc) for the standing train `name`; `merge()`, `join()`: the round's post-merge merges and
    the open train's join round (their lines). The lines printed."""
    url = run_before(train_state.lines(main), name)
    row = concluded(main, rid_of(url)) if url else None
    if not row or row.get("status") != "completed" or row.get("conclusion") == "success":
        return []  # D9: no red (or the run still runs: next_train.wait gave up), no wait
    rid, began, limit, lines, told, woke, seen = rid_of(url), clock(), TIMEOUT, [], None, False, {}
    limit = limit if limit is not None else wall(row, now())
    while True:
        lines += merge()
        rows = train_state.lines(main)
        train = train_state.standing(rows)
        if not train or train.get("train") != name:
            return lines + [f"next train: train {name} no longer stands: the fix wait ends"]
        left = holding(main, train, rows, entry_of(main, rid), read, seen)
        if left == []:
            lines.append(f"next train: every red of run {rid} has its fix car or a named reason: the push goes")
            print(lines[-1], flush=True)
            return lines
        if (text := says(left, url)) != told:
            told = text
            lines.append(f"next train: {text}")
            print(lines[-1], flush=True)
        lines += join()
        if not woke and clock() - began >= limit:
            woke = True
            wake(main, train, url, left, clock() - began, now())
            lines.append(f"next train: the fixes of run {rid} took over {int(limit)} s: the tollman is woken, "
                         "the push still waits")
            print(lines[-1], flush=True)
        sleep(POLL)


def reason(main: str, url: str, why: str, red: str | None = None) -> str:
    rid = rid_of(url)
    wire.update(main, rid, lambda e: e.setdefault("reasons", {}).update({red or ALL: why}))
    return rid


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("reason",))
    p.add_argument("--repo", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--red", default=None)
    p.add_argument("--why", required=True)
    a = p.parse_args(argv)
    rid = reason(mtm_scan.main_checkout(a.repo), a.run, a.why, a.red)
    print(f"run {rid}: {a.red or 'every red'} has a named reason ({a.why}): the waiting push looks again")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
