"""The wagon master's train state (hal2 plan 0294 step 6): `train.jsonl` in its state folder, an event log the
skill's `manifest.toml` declares (hal2's .adr/role-folder-formats.md: `schema`, `at` in UTC with `Z`, `kind`,
`slot`). Every change of a train is one appended line, written by one function of `engine.py`:

  formed     slot: the carrier (the wagon master's field); `train` (its name, `<car>+<car>@<at>`), `cars`
             ([{field, branch, head, plan}] in the order they are merged), `base` (the field's head before them)
  yard       the yard's work rides as the train's first car (yard.py, step 8): `commit` (in the field; none
             when the barn holds every file as it is), `files` ([{path, hash}]: the hash of what each path
             carried, none for a deletion)
  started    the landing's process: `pid`, `log`; written again by every restart
  red        the landing did not land: `status` (the landing's), `run` (the land run's address), `why`
  retry      the session's word after a red train: the same train lands again
  unhitched  slot: the field whose ready mark went; `why`; `train` when it was a car of the red train. The slot
             `yard` (YARD): the yard's car, with its `files`, which stay out of every train until they change
  landed     the train is in the barn: `cars`, `run`, `commit`; `yard` when the yard rode ({dropped, kept, pulled,
             why}: what yard.settle did there)
  cleared    the train is no more (a car that did not merge, a split after red, a leftover mark): `why`

`standing` folds the lines into the train that stands, or None between trains: its `state` is `formed` (merged or
merging, no landing started), `landing`, `red` (waits for the session), `retry`, or `split` (a car was unhitched
after red: the rest forms again). The landing's own output is the text log `train-landing.log`, rewritten by every
start; `result` is its last JSON line.
"""

import datetime as dt
import json
import os
import subprocess
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import board
import mtm_scan

ROLE = "wagon-master"
FILE, LOG = "train.jsonl", "train-landing.log"
SCHEMA = 1
YARD = "yard"  # the yard as a car: no field, never in the queue's mark
KINDS = ("formed", "yard", "started", "red", "retry", "unhitched", "landed", "cleared")


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
                     "base": e.get("base"), "state": "formed", "starts": 0, "pid": None, "unhitched": [], "yard": []}
        elif not train or e.get("train") != train["train"]:
            continue
        elif kind == "yard":
            train["yard"] = e.get("files", [])
        elif kind == "started":
            train.update(state="landing", pid=e.get("pid"), starts=train["starts"] + 1, started=e.get("at"))
        elif kind == "red":
            train.update(state="red", status=e.get("status"), run=e.get("run"), why=e.get("why", ""))
        elif kind == "retry":
            train.update(state="retry")
        elif kind == "unhitched":
            train["unhitched"].append({"field": e.get("slot"), "why": e.get("why", "")})
            train["state"] = "split"
        else:  # landed, cleared
            train = None
    return train


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
    try:
        command = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                                 timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return True
    return not command or "engine.py" in command


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
