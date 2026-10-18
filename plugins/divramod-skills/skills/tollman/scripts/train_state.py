"""The tollman's train state (hal2 plan 0294 step 6): `train.jsonl` in its state folder, an event log the
skill's `manifest.toml` declares (hal2's .adr/role-folder-formats.md: `schema`, `at` in UTC with `Z`, `kind`,
`slot`). Every change of a train is one appended line, written by one function of `engine.py`:

  formed     slot: the carrier (the tollman's field); `train` (its name, `<car>+<car>@<at>`), `cars`
             ([{field, branch, head, plan}] in the order they are merged), `base` (the field's head before them);
             `pushed` when the carrier's remote branch still held an earlier train and went back on the base, or why
             it did not (plan 0313 step 14)
  yard       the yard's work rides as the train's first car (yard.py, step 8): `commit` (in the field; none
             when the barn holds every file as it is), `files` ([{path, hash}]: the hash of what each path
             carried, none for a deletion)
  regenerated  a car's conflicts in generated files took the barn's side (generated.py, plan 0313 step 8):
             `commit` (the train's last, none when nothing differed), `files` (the paths written again), `why`
  pretest    the train's pretest before its landing (pretest_train.py, plan 0349 D75): `seconds`, `result`
             (green, red, skipped, none), `jobs` ([{job, key, state, seconds, result, why}]: state cached, run,
             skipped or not needed), `why`; its jobs' output in the text log `train-pretest.log`
  started    the landing's process: `pid`, `log`; written again by every restart; after a `retry` also `commit`,
             the empty commit that gives the landing a new candidate and so a fresh run (plan 0313 step 13)
  run        the landing's land run, found by watch.py while it lands (plan 0360 step 5): `run` (its address); the
             latest after the last `started` is this start's (`land_run`)
  red        the landing did not land: `status` (the landing's), `run` (the land run's address), `why`
  order      a fix order (orders.py, plan 0360 step 6, D6, D29): `field` (a car's, or `main`: the tollman's own),
             `branch` (`<NN>-train-fix`, `tollman-train-fix`), `base` (the carrier's head it branches from), `why`,
             `run`, `id`; open until its `fixed` line
  fixed      a fix order answered: `field`, `id`, `sha` (the fix), `commit` (the carrier's merge of it)
  pause      a smuggle paused the train's landing (pause.py, plan 0360 step 18, D58): `field` (the smuggle's slot),
             `seq`, `since` (the queue's `paused_by`), `run` (the land run watched then: the run the pause cancels,
             triage.paused_by); the train `paused` until its `resumed` line
  resumed    the carrier's ticket lost `paused_by`: hal2-git resumed the landing on the new main; `field` (the
             smuggles); the train `landing` again, its land run forgotten (watch.py finds the newer one)
  retry      the session's word after a red train, or the code's after a runner fault (`why` starting `runner`,
             triage.py): the same train lands again; `runner_retries` counts the code's in a row
  barn       slot: a field whose head was in the barn already when the tollman woke from smuggle mode (modes.py, plan
             0360 step 25, D75, D76): `head`, `how` (`hitch`: its ready mark cleared; `formed`: it left the formed
             train `train`; `running`: only recorded, the running train `train` carries nothing new of it)
  unhitched  slot: the field whose ready mark went; `why`; `train` and `by: user` when it was a car of the red train,
             taken out by the user's own command (plan 0360 D3: never the session's). The slot `yard` (YARD): the
             yard's car, with its `files`, which stay out of every train until they change
  landed     the train is in the barn: `cars`, `run`, `commit`; `yard` when the yard rode ({dropped, kept, pulled,
             why}: what yard.settle did there)
  cleared    the train is no more (a car that did not merge in its form, the user's split or breakup, a leftover
             mark): `why` and `pushed` when the carrier's remote branch went back on the base, or why it did not

`standing` folds the lines into the train that stands, or None between trains: its `state` is `formed` (merged or
merging, no landing started), `landing` (its pretest's result in `pretest`), `red` (frozen, waits for its fix or the
session's retry), `fixing` (red with fix orders open, `orders`: frozen as red), `retry` (also once the last order is
`fixed`: `fixed` true, the merge is the new candidate), `paused` (a smuggle paused its landing, `pauses`: frozen,
pause.py), or `split` (the user unhitched a car after red: the rest
forms again). The landing's own output is the text log `train-landing.log`, rewritten by every start; `result` is its last JSON line.
"""

import datetime as dt
import json
import os
import subprocess
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import board
import mtm_scan

ROLE = "tollman"
FILE, LOG = "train.jsonl", "train-landing.log"
SCHEMA = 1
YARD = "yard"  # the yard as a car: no field, never in the queue's mark
KINDS = ("formed", "yard", "regenerated", "pretest", "started", "run", "red", "order", "fixed", "pause", "resumed",
         "retry", "unhitched", "barn", "landed", "cleared")
RUNNER = "runner"  # a retry's `why` that starts so is the code's after a runner fault (triage.py)


def utc(now: dt.datetime | None = None) -> str:
    """RFC 3339 UTC with `Z` and whole seconds; a time without a zone is this machine's local time."""
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def folder(main: str) -> Path:
    return mtm_scan.state_dir(main, ROLE)


def append(main: str, kind: str, slot: str, now: dt.datetime | None = None, **keys) -> dict:
    """One line, one write under O_APPEND; a key without a value is left out."""
    if kind not in KINDS:
        raise ValueError(f"no train state kind {kind!r}")
    line = {"schema": SCHEMA, "at": utc(now), "kind": kind, "slot": slot or "-",
            **{k: v for k, v in keys.items() if v is not None}}
    fd = os.open(folder(main) / FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(line) + "\n").encode())
    finally:
        os.close(fd)
    board.safely(main, f"train state {kind}", board_line, line)
    return line


def board_line(main: str, line: dict) -> None:
    """The message board's part of a change (board.py, step 7): a line for `formed`, `landed`, `red`, `unhitched`.
    A red train's cars are the standing train's. The yard is no field: its unhitch is no board line (D21)."""
    if line.get("slot") == YARD:
        return
    board.on_state(main, line, standing(lines(main)) if line["kind"] == "red" else None)


def lines(main: str) -> list[dict]:
    """The state's lines; one that does not parse (a torn last line) is skipped."""
    f, out = folder(main) / FILE, []
    for text in f.read_text().splitlines() if f.exists() else []:
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("kind"):
            out.append(row)
    return out


def standing(rows: list[dict]) -> dict | None:
    """The train that stands as the lines say (see the module doc), or None."""
    train = None
    for e in rows:
        kind = e["kind"]
        if kind == "formed":
            train = {"train": e.get("train"), "at": e.get("at"), "carrier": e.get("slot"), "cars": e.get("cars", []),
                     "base": e.get("base"), "state": "formed", "starts": 0, "pid": None, "unhitched": [], "yard": [],
                     "runner_retries": 0, "land_run": None, "orders": [], "fixed": False, "pauses": [],
                     "in_barn": []}
        elif not train or e.get("train") != train["train"]:
            continue
        elif kind == "yard":
            train["yard"] = e.get("files", [])
        elif kind == "regenerated":
            train["regenerated"] = e.get("commit")
        elif kind == "pretest":
            train["pretest"] = e.get("result")
        elif kind == "started":
            train.update(state="landing", pid=e.get("pid"), starts=train["starts"] + 1, started=e.get("at"),
                         land_run=None, fixed=False, since=None)
        elif kind == "run":
            train["land_run"] = e.get("run")
        elif kind == "red":
            train.update(state="red", status=e.get("status"), run=e.get("run"), why=e.get("why", ""))
        elif kind in ("order", "fixed"):
            fix(train, e)
        elif kind == "pause":
            train["pauses"].append({k: e.get(k) for k in ("field", "seq", "since", "run")})
            if train["state"] != "paused":
                train.update(paused_from=train["state"], state="paused")
        elif kind == "resumed":
            if train["state"] == "paused":
                resume(train)
        elif kind == "retry":
            runner = str(e.get("why", "")).startswith(RUNNER)
            train.update(state="retry", retried=e.get("why", ""), runner_retries=(train["runner_retries"] + 1) * runner)
        elif kind == "barn":  # a car already in the barn (smuggled, modes.py): a formed train's leaves it (D76)
            train["in_barn"].append(e.get("slot"))
            train["cars"] = [c for c in train["cars"] if e.get("how") != "formed" or c["field"] != e.get("slot")]
        elif kind == "unhitched":
            train["unhitched"].append({"field": e.get("slot"), "why": e.get("why", ""), "by": e.get("by")})
            train["state"] = "split"
        else:  # landed, cleared
            train = None
    return train


def fix(train: dict, e: dict) -> None:
    """An `order` opens a fix order (the train `fixing`), a `fixed` closes one; the last closed: `retry`."""
    if e["kind"] == "order":
        train["orders"].append({k: e.get(k) for k in ("id", "field", "branch", "base", "why", "run", "at")})
        train["state"] = "fixing"
        return
    train["orders"] = [o for o in train["orders"] if o["id"] != e.get("id")]
    if not train["orders"]:
        train.update(state="retry", retried=f"fixed: {e.get('id')}", fixed=True, runner_retries=0)


def resume(train: dict) -> dict:
    """A paused train resumed: its state before the pause, its land run forgotten; watch.py looks for runs created
    since the pause (`since`), so the cancelled one is never taken for the resumed landing's."""
    train.update(state=train.pop("paused_from", None) or "landing", land_run=None, resumed=len(train["pauses"]),
                 since=train["pauses"][-1].get("since"))
    return train


def land_run(rows: list[dict]) -> str | None:
    """The standing train's land run of its current start (a `run` line after its last `started`), or None."""
    return (standing(rows) or {}).get("land_run")


def yard_past(rows: list[dict]) -> dict:
    """What yard.sort needs of the past: `carried` ({path: [hash]}: what the yard brought into a train, so a barn
    file that is the yard's own may be changed by it again) and `refused` ({path: hash}: the files of a yard car a
    session unhitched from a red train)."""
    past: dict = {"carried": {}, "refused": {}}
    for e in rows:
        for f in e.get("files", []) if e["kind"] == "yard" else []:
            past["carried"].setdefault(f["path"], []).append(f.get("hash"))
        for f in e.get("files", []) if e["kind"] == "unhitched" and e.get("slot") == YARD else []:
            past["refused"][f["path"]] = f.get("hash")
    return past


def carries(top: str) -> bool:
    """The frame's question (roles.Wiring.carries, D22): does the field `top` hold a train now?"""
    return standing(lines(mtm_scan.main_checkout(top))) is not None


def alive(pid) -> bool:
    """The landing's detached process lives: the pid exists and is still `engine.py land` (a pid the system gave
    to another process since, after a restart of the machine, is not it). Where `ps` cannot say, the pid decides."""
    if not mtm_scan.pid_alive(pid):
        return False
    command = command_of(pid)
    return not command or "engine.py" in command


def command_of(pid) -> str | None:
    """`ps`'s command line of the process `pid`: "" when it names none, None when `ps` cannot run."""
    try:
        return subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def result(main: str) -> dict | None:
    """What the landing printed last: the last line of its log that is a JSON object with a `status`."""
    f = folder(main) / LOG
    for text in reversed(f.read_text(errors="replace").splitlines() if f.exists() else []):
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("status"):
            return row
    return None
