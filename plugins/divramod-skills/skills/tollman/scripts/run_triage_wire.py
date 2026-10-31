#!/usr/bin/env python3
"""The triage of a finished land run, wired into the tollman's watch (hal2 plan 0490 step 3; D6, D9, D13): the run's
`workflow finished` event (watch_events.py) starts it beside the next train, never before it.

1. `started`: on a fresh `finished` event of the watched run the watch (minute.events, in the 1-minute pass and in a
   round alike, never in a dry one) marks the run due and spawns this script's `run` detached (SPAWN), once per run;
   its only action is a `record` keyed `run-triage:<run id>`. The pass goes on at once: its chain forms the next
   train, and the child first waits for the tick lock, so it reads only after the pass or round that started it has
   carried out its actions (the next train formed, D6), then holds no lock. A run marked due by another path
   (stack_red.watch, `run_triage_wire.py due`) is spawned by the next pass the same way.
2. `run` (the child): gathers the finished run (run_triage_gather.gather; the signatures of the runs triaged before,
   `kept`, so no gh call for those), triages (run_triage.triage), plans the dispatch (run_triage_plan.plan:
   run_triage_act.actions, the slow moved lanes) and writes the planned actions and the run's signatures.
A fresh `step-failed` event (a red step of a job that still runs, plan 0490 step 25) and the `job failed` of a job a
step order went out for are run_triage_step_act.py's, planned in the same pass (`started`), never in a child.

3. `pending`: every pass and round adds the planned actions of the triages written in the last PENDING hours after
   its own, and a waiting push's timeout wake (`push`, fix_wait.py, plan 0490 step 21); `tick.fresh` drops the done
   keys, so each runs once, in the tollman's own execution. A child that failed (its `error`) or never wrote (STUCK
   minutes after its start) is one wake (`triage-failed:<run id>`).

The pipeline's field (L132) is the optional `pipeline_field:` of the tollman's ROLE.md front matter (the user's
word); without it a pipeline red no car caused is `unsure` (the wake).

`run-triage.json` in the tollman's state folder: {schema, runs: [{run, url, train, started, due, spawned, at, units,
actions, reds, error, reasons, push}]} (`reds`, `reasons`, `push`: fix_wait.py), the last KEEP runs (its retention),
changed under `run-triage.lock`, written atomically.

  run_triage_wire.py due --repo <field> --run <url> [--train <name>]   mark a finished run due (the next pass spawns)
  run_triage_wire.py run --repo <field> --run <url> [--train <name>]   the triage, now (what the spawned child runs)
"""

import argparse
import datetime as dt
import fcntl
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import leavers
from tick import act

FILE, LOCK = "run-triage.json", "run-triage.lock"
SCHEMA = 1
KEEP = 8  # runs kept: their signatures feed the next runs' repeat check (run_triage_gather.PREVIOUS)
PENDING = 6  # hours a written triage's actions are offered to the rounds
STUCK = 30  # minutes after its start a triage that wrote nothing is told
KIND = "run-triage"
CLI = Path(__file__).resolve()
SPAWN = subprocess.Popen  # the detached child (the tests replace it: no process leaves a test)


def utc(now: dt.datetime | None = None) -> dt.datetime:
    return now or dt.datetime.now(dt.timezone.utc)


def state(main: str) -> dict:
    doc = leavers.read(main, FILE, {})
    return doc if isinstance(doc, dict) and doc.get("schema") == SCHEMA else {"schema": SCHEMA, "runs": []}


@contextmanager
def locked(main: str):
    folder = leavers.folder(main)
    if not folder.is_dir():
        yield
        return
    with (folder / LOCK).open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def update(main: str, rid: str, change) -> dict:
    """The run's entry after `change(entry)` (a new one when missing), kept with the last KEEP runs."""
    with locked(main):
        runs = state(main)["runs"]
        entry = next((r for r in runs if r.get("run") == rid), None) or {"run": rid}
        change(entry)
        runs = [r for r in runs if r.get("run") != rid] + [json.loads(json.dumps(entry, default=sorted))]
        leavers.write(main, FILE, {"schema": SCHEMA, "runs": runs[-KEEP:]})
    return entry


def due(main: str, url: str, train: str | None, at: str | None = None, now: dt.datetime | None = None) -> str:
    """Mark the finished run at `url` due (kept as it is when known); its id."""
    rid = url.rsplit("/", 1)[-1]
    update(main, rid, lambda e: e.update({k: v for k, v in (("url", url), ("train", train), ("started", at),
                                                           ("due", utc(now).isoformat(timespec="seconds")))
                                          if k not in e}))
    return rid


def spawn(top: str, main: str, now: dt.datetime | None = None) -> list[str]:
    """The due runs' children, started detached; the ids started."""
    out = []
    for r in [r for r in state(main)["runs"] if r.get("due") and not r.get("spawned")]:
        log = leavers.folder(main) / "run-triage.log"
        with (log.open("w") if log.parent.is_dir() else open(os.devnull, "w")) as sink:  # the last child's output
            SPAWN([sys.executable, str(CLI), "run", "--repo", top, "--run", r.get("url") or "", "--train",
                   r.get("train") or ""], cwd=top, stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT,
                  start_new_session=True)
        update(main, r["run"], lambda e: e.update(spawned=utc(now).isoformat(timespec="seconds")))
        out.append(r["run"])
    return out


def started(top: str, main: str, fresh: list[dict], watched: dict, dry: bool = False) -> list[dict]:
    """1.: on a fresh `finished` event of the watched run (`watched`: watch_events.state) its triage marked due and,
    with any other due run, spawned (never in a dry round); the `record` of each started run."""
    rid = str(watched.get("run") or "")
    hit = rid and any(e["kind"] == "finished" and e["key"] == f"done:{rid}" for e in fresh)
    steps = []
    if any(e["kind"] in ("step-failed", "job-failed") for e in fresh):  # plan 0490 step 25: a red step, at once
        import run_triage_step_act
        steps = run_triage_step_act.on_events(top, main, fresh, watched, dry)
    if dry:
        return steps + ([record(rid)] if hit else [])
    if hit:
        due(main, watched.get("url") or "", watched.get("train"), watched.get("started"))
    return steps + [record(r) for r in spawn(top, main)]


def record(rid: str) -> dict:
    return act("trains", KIND, "record", "-", key=f"{KIND}:{rid}",
               text=f"land run {rid} finished: its triage runs beside the next train")


def pending(main: str, now: dt.datetime | None = None) -> list[dict]:
    """3.: the planned actions of the triages written in the last PENDING hours; a failed or stuck one's wake."""
    out = []
    for r in state(main)["runs"]:
        written, began = when(r.get("at")), when(r.get("spawned"))
        if written and utc(now) - written <= dt.timedelta(hours=PENDING):
            out += r.get("actions") or []
        held = r.get("push") or {}  # the waiting push's timeout wake (fix_wait.py, plan 0490 step 21)
        if (at := when(held.get("at"))) and utc(now) - at <= dt.timedelta(hours=PENDING) and held.get("action"):
            out.append(held["action"])
        stuck = not written and began and utc(now) - began > dt.timedelta(minutes=STUCK)
        if (r.get("error") or stuck) and (written or began) and utc(now) - (written or began) <= dt.timedelta(
                hours=PENDING):
            why = r.get("error") or f"no result {STUCK} minutes after its start"
            out.append(act("trains", "triage-failed", "wake", key=f"triage-failed:{r['run']}",
                           text=f"the triage of land run {r.get('url') or r['run']} failed ({why[:300]}): see "
                                f"run-triage.log in the tollman's state folder, then `python3 {CLI} run --repo <field> "
                                f"--run {r.get('url')} --train {r.get('train')}`"))
    return out


def when(text) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(text)) if text else None
    except ValueError:
        return None


def pipeline_field(top: str) -> str | None:
    """The optional `pipeline_field:` of the tollman's ROLE.md front matter (L132), else None."""
    import due as due_
    path = Path(top) / "roles" / "tollman" / "ROLE.md"
    value = due_.front_matter(path.read_text()).get("pipeline_field") if path.is_file() else None
    return (str(value).strip() or None) if value is not None else None


def train_of(rows: list[dict], name: str | None) -> tuple[dict, dict | None]:
    """(the run's train: the standing one of that name, else as it stood before it landed; the train standing now)."""
    import post_merge
    import train_state
    standing = train_state.standing(rows)
    if standing and standing.get("train") == name:
        return standing, standing
    return post_merge.past(rows, name) or {"train": name or "?", "cars": []}, standing


def after_the_round(top: str) -> None:
    """D6: wait until the pass or round that started this child has carried out its actions (it holds the tick lock
    while it does: the next train is formed then); then hold no lock."""
    import role_cli
    import tollman
    with (role_cli.state(top, tollman.WIRING) / "tick.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)


def run(top: str, url: str, train: str | None, ctx: dict | None = None, now: dt.datetime | None = None,
        wait=after_the_round, **kw) -> dict:
    """2.: triage the finished run at `url` and keep its planned actions; the entry kept. `ctx`: the round's context
    (tick.context; read here when None); `kw` go to run_triage_plan.plan (a test's `gather`)."""
    import mtm_scan
    import run_triage_plan  # 2. as data (a triage's modules load only in its child)
    main = mtm_scan.main_checkout(top)
    wait(top)
    rid = url.rsplit("/", 1)[-1]
    kept = {r["run"]: r.get("units") or {} for r in state(main)["runs"] if r.get("at") and not r.get("error")}
    try:
        got = run_triage_plan.plan(top, main, url, train, ctx, kept, pipeline_field(top), utc(now), train_of, **kw)
        error = None
    except Exception as e:  # noqa: BLE001  (any failure is kept and becomes one wake, never a silent loss)
        got, error = {"units": {}, "actions": []}, f"{type(e).__name__}: {e}"
    return update(main, rid, lambda e: e.update(url=url, train=e.get("train") or train, error=error,
                                                at=utc(now).isoformat(timespec="seconds"), **got))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("due", "run"))
    p.add_argument("--repo", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--train", default="")
    a = p.parse_args(argv)
    import mtm_scan
    if a.cmd == "due":
        print(f"run {due(mtm_scan.main_checkout(a.repo), a.run, a.train or None)} due: the next pass triages it")
        return 0
    entry = run(a.repo, a.run, a.train or None)
    print(f"run {entry['run']}: {len(entry.get('actions') or [])} actions" +
          (f", error {entry['error']}" if entry.get("error") else ""))
    return 1 if entry.get("error") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
