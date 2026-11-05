"""The tollman's train state (hal2 plan 0294 step 6): `train.jsonl` in its state folder, an event log the
skill's `manifest.toml` declares (hal2's .adr/role-folder-formats.md: `schema`, `at` in UTC with `Z`, `kind`,
`slot`). Every change of a train is one appended line, written by one function of `engine.py`:

  formed     `number` (the train's number, plan 0398 D4: `next_number`; none on a train formed before it), the carrier (its key above), the train's own worktree `tollman-train-<plan>-...` (train_wt.py, plan 0375 D5; the
             tollman's field before), `worktree` (its path); `train` (its name, `<car>+<car>@<at>`), `cars`
             ([{field, branch, head, plan}] in the order they are merged), `base` (the field's head before them);
             `pushed` when the carrier's remote branch still held an earlier train and went back on the base, or why
             it did not (plan 0313 step 14); `alone_next`: the alone cars that ride alone in the next train, ahead of
             every later hitch (trains.owed, plan 0610 D15)
  yard       the yard's work rides as the train's first car (yard.py, step 8): `commit` (in the field; none
             when the barn holds every file as it is), `files` ([{path, hash}]: the hash of what each path
             carried, none for a deletion)
  regenerated  a car's conflicts in generated files took the barn's side (generated.py, plan 0313 step 8):
             `commit` (the train's last, none when nothing differed), `files` (the paths written again), `why`
  joined     a wagon joined the standing train before its push (open_train.py, train_join.py; plan 0610 D17): `cars`
             (one car; a riding field's newer head takes its car's place, E10), `base`, `commit`, `merged` (false: the
             next start merges it), its jobs' pretest (`result`, `seconds`, `jobs`, `why`), `mark` (a refusal)
  declined   a join undone, before plan 0610 (E6: none now): `field`, `head`, `why`
  resolving  a car whose merge conflicts rides on (plan 0522 D18, resolve.py): `field`, `head`, `files`, `ahead` (the
             cars merged before it, [] the barn), `base` (the carrier's head), `id`, `branch`
             (`<NN>-train-<n>-<a>-resolve`),
             `ref` (the remote branch it starts from, `train-<n>-<a>`), `unpublished` (why the base is not on
             origin); the train `resolving` until its `resolved` line
  resolved   the car's foreman resolved it on the train's branch: `field`, `id`, `sha`, `commit`; the train `formed`
  pretest    the train's pretest before its landing (pretest_train.py, plan 0349 D75): `seconds`, `result`
             (green, red, incomplete, skipped, none), `jobs` ([{job, key, state, seconds, result, why}]: state
             cached, run, skipped or not needed), `why`, `tree` (the tree of the HEAD it tested: a new tree is
             pretested again, plan 0522); its jobs' output in the text log `train-pretest.log`
  started    the landing's process: `pid`, `log`, `land_ref` (the train's own branch, landed on `land/<land_ref>`:
             `train-<number>-<start>`, the mark's `--train/--attempt`, plan 0398; `train-<plan>-...` before it); written again by every restart; after a `retry` also
             `commit`, the empty commit that gives the landing a new candidate and so a fresh run (plan 0313 step 13)
  roles      the role cars (role_cars.py, plan 0610 D18), once per train right before its first push: `merged`
             ([{field, head}]: the tollman's and the farmer's branches merged as the train's last cars), `out`
             ([{field, head, why, times}]: one that did not merge, owed: it rides the next train first, D24); with
             `place: first` an owed car merged at the forming (or a stopped train's retry); `stop` ({field, head,
             why}): left out a second time in a row, the train `stopped` until that car merges
  alone      an alone car (gate_car.py) hitched while the train stood (open_train.owe, plan 0610 D15): `field`, `head`,
             `why`; it rides alone in the very next train, as the `formed` line's `alone_next` (trains.owed)
  attempt    a restart got past its alive, adopt and hold checks and started nothing (engine.restart, hal2 plan 0620
             D5): it went red on a car's light checks (proof_red) or its fresh commit, branch or mark was refused;
             `attempt`, the number it raises the train's to (train_fold.attempt: a `started` line raises it too),
             which keys the round's restart `retry:<train>:<attempt>`
  push       the landing's push (engine.land, plan 0560 step 3, D5): `head`, the carrier's HEAD it lands, after the wait and
             the post-merge fixes (head_guard.py: never pushed again once its run is red)
  run        the landing's land run, found by watch.py while it lands (plan 0360 step 5): `run` (its address); the
             latest after the last `started` is this start's (`land_run`); the train's first one also has
             `local_phase_seconds` (formed → the run's creation, plan 0467 D21, D23)
  red        the landing did not land: `status` (the landing's), `run` (the land run's address), `why`; `head` when this
             start pushed (its `push` line's): the head of a red run
  order      a fix order (orders.py, plan 0360 step 6, D6, D29): `field` (a car's, or `main`: the tollman's own),
             `branch` (`<NN>-train-<n>-<a>-fix`, `tollman-train-<n>-<a>-fix`; a train without a number or none:
             `<NN>-train-fix`, `tollman-train-fix`; run_names.py), `base` (the carrier's head it branches from), `why`,
             `run`, `id`, `jobs` (the gate jobs its fix must turn green: fix_proof.py, plan 0522 D5); open until its
             `fixed` line; one with `also` (an open early order's id) adds its `jobs` and `why` to that order, a
             car's next red job while the run runs (plan 0522 D16). One written while the train lands is *early*
             (plan 0383 D5, the triage named one car while the run runs): the train stays `landing`, its `red` makes it `fixing`.
             One with `post` (the landed train's name: a red after its merge job, post_merge.py, plan 0383 step 6,
             D6) never changes the state: it is in `post`, carried to the next train formed while it is open (so
             is an early order of a train that landed green), and its fix is merged into that train before its run
             starts (next_train.py)
  fixed      a fix order answered: `field`, `id`, `sha` (the fix), `commit` (the carrier's merge of it), `unproven`
             (the session's why when it took the fix without proof, plan 0522 D5)
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
  woke       slot (names-ok: every line's key): a car's field that had no session when the train's order (`id`)
             needed its foreman: started (foreman_wake.py, plan 0522 D21), `field`, `why`; changes no state
  cleared    the train is no more (a car that did not merge in its form, the user's split or breakup, a leftover
             mark): `why` and `pushed` when the carrier's remote branch went back on the base, or why it did not

`standing` and the folding: train_fold.py (split out by hal2 plan 0610 step 9, small-files).
"""

import datetime as dt
import fcntl
import json
import os
import subprocess
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import roletime
from train_fold import (ORDER_KEYS, RUNNER, YARD, add_cars, attempt, carried, fix, land_run, restart_key,  # noqa: F401
                        resume, standing, yard_past)  # the callers' `train_state.standing` (and the rest) stay

ROLE = "tollman"
FILE, LOG, NUMBER = "train.jsonl", "train-landing.log", "train-number"
SCHEMA = 1
KINDS = ("formed", "yard", "regenerated", "joined", "declined", "resolving", "resolved", "pretest", "started", "push", "run",
         "red", "order", "fixed", "pause", "resumed", "retry", "unhitched", "barn", "landed", "cleared", "woke",
         "roles", "alone", "attempt")


def utc(now: dt.datetime | None = None) -> str:
    """RFC 3339 UTC with `Z` and whole seconds; a time without a zone is this machine's local time."""
    return roletime.now(now)


def folder(main: str) -> Path:
    return mtm_scan.state_dir(main, ROLE)


def next_number(main: str) -> int:
    """The next train number (hal2 plan 0398 D4): a counter file `train-number` in the state folder, outside the
    dated archive folders so it survives them, read and bumped under a lock; the first train is 1."""
    f = folder(main)
    f.mkdir(parents=True, exist_ok=True)
    with (f / NUMBER).open("a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        last = int(fh.read().strip() or 0)
        fh.seek(0)
        fh.truncate()
        fh.write(f"{last + 1}\n")
    return last + 1


def peek_number(main: str) -> int:
    """The number `next_number` gives next, read without taking it (a forming names its carrier by it first)."""
    try:
        return int((folder(main) / NUMBER).read_text().strip() or 0) + 1
    except (OSError, ValueError):
        return 1


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
    __import__("board").safely(main, f"train state {kind}", board_line, line)  # lazily: a quiet pass loads no board
    return line


def attempted(main: str, field: str, train: dict, now: dt.datetime | None = None) -> dict:
    """The `attempt` line of a restart past its checks that started nothing (plan 0620 D5): its key raised by one."""
    return append(main, "attempt", field, now, train=train["train"], attempt=attempt(train) + 1)


def board_line(main: str, line: dict) -> None:
    """The message board's part of a change (board.py, step 7): a line for `formed`, `landed`, `red`, `unhitched`.
    A red train's cars are the standing train's. The yard is no field: its unhitch is no board line (D21)."""
    if line.get("slot") == YARD:
        return
    __import__("board").on_state(main, line, standing(lines(main)) if line["kind"] == "red" else None)


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


def carries(top: str) -> bool:
    """The frame's question (roles.Wiring.carries, D22): does the field `top` hold a train now? Since plan 0375 a
    train rides in its own worktree, so the tollman's field holds none (only one formed before still stands in it)."""
    train = standing(lines(mtm_scan.main_checkout(top)))
    return train is not None and train["carrier"] == Path(top).name


LANDING_COMMANDS = ("engine.py", "worktree merge-to-main")


def alive(pid) -> bool:
    """The landing's detached process lives: the pid exists and is still `engine.py land` (a pid the system gave
    to another process since, after a restart of the machine, is not it). Where `ps` cannot say, the pid decides."""
    if not mtm_scan.pid_alive(pid):
        return False
    command = command_of(pid)
    # an adopted landing's pid is hal2-git's merge-to-main itself (adopt.py, 2026-11-04): it lives as much as its engine
    return not command or any(mark in command for mark in LANDING_COMMANDS)


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
