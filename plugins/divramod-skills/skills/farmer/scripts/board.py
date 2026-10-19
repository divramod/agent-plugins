#!/usr/bin/env python3
"""A role's message board (hal2 plan 0294 step 7, decisions D3, D14, D21; plan 0290 step 3, D23): `roles/<role>/board.jsonl`
in the role's field, never the yard, for the tollman and the farmer (`--role`, the tollman by default). Every message
between the role and a foreman, and every change of the queue's trains, is one line the farm view reads; field 09's
follower tails the file. The farmer's board holds the kinds `message`, `ack` and `note` only, copied by `sync` from
its journal `log.jsonl` (read by this script alone; hal2 never parses a journal); its tick runs `sync --role farmer`.

An event log (hal2's .adr/role-folder-formats.md): one JSON line per event, written with O_APPEND in one write,
never rewritten; pruned only by whole lines from its start (PRUNE_AT: the record's 2 MB), by rename, so a tail
that lost its place starts again at the file's first line. The manifest says so. Only this module writes it.

A line: `schema`, `at` (RFC 3339 UTC with `Z`), `kind`, `slot` (the envelope's: the field the line concerns), `from`,
`to` (field names as the queue has them: `09`, `tollman-hal2`, `farmer-hal2`; `-` where no one single field is
meant; never a pane id, session id or title), `text`, and by kind (the names are agreed with field 09, D21):

  ready      a ticket was marked ready: from the field, to the tollman; `head`
  unhitched  a mark cleared: from the tollman, to the field; the reason in `text`; `train` when it was a car
  train      a train formed: `cars` (field names in the queue's order), `train` (its name)
  landed     a train is in the barn: `cars`, `run` (the land run's address), `commit`
  red        a train did not land: `cars`, `run`, `status`, the reason in `text`
  message    one the tollman sent: `id` is its ack id
  ack        one it got: `id` of the message it answers, `status` (started, done or refused)
  note       one nobody is sent (plan 0360 step 8, D9): from the tollman to the field it is for (the farmer's),
             which reads the board when it asks; `text`. From the frame's `record` entries of the kinds in NOTES

  board.py post --kind <kind> --from <field> --to <field> [--text ..] [--id ..] [--cars a,b] [--run ..] [--head ..]
                [--status ..] [--train ..] [--commit ..] [--role <role>] [--repo <dir>]   one line
  board.py list [--kind <kind>] [--last <n>] [--json] [--role <role>] [--repo <dir>]       the lines (newest last)
  board.py sync [--role <role>] [--repo <dir>]
      the frame's messages, acks and notes (its log.jsonl: `ask-ack`, `ack`, a `record` of a kind in the role's
      notes: NOTES for the tollman, `note` for the farmer) as `message`, `ack` and `note` lines, each once

A post that fails never fails a round: `safely` logs it to the frame's log (`board-failed`) and goes on.
"""

import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import sys
from pathlib import Path

import mtm_scan  # the tollman's scripts reach this folder through its farmer_frame

ROLE = "tollman"  # the default role of every function and of `--role`
ROLES = ("tollman", "farmer")
FILE, LOCK = "board.jsonl", "board.lock"
SCHEMA = 1
KINDS = ("ready", "unhitched", "train", "landed", "red", "message", "ack", "note")
KINDS_OF = {"tollman": KINDS, "farmer": ("message", "ack", "note")}
STATUSES = ("started", "done", "refused")
PRUNE_AT, PRUNE_TO = 2 * 1024 * 1024, 1024 * 1024  # over 2 MB (the record's event log): the newest 1 MB stay
FIELD = re.compile(r"^(-|[a-z0-9][a-z0-9-]*)$")
NOT_FIELD = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")  # a session id
AT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
ID = re.compile(r"^[A-Za-z0-9-]+-[0-9]+$")
NEEDS = {"ready": ("head",), "unhitched": ("text",), "train": ("cars",), "landed": ("cars",), "red": ("cars",),
         "message": ("id", "text"), "ack": ("id", "status"), "note": ("text",)}
TO_SLOT = ("unhitched", "message", "note")  # the lines the tollman sends: their slot is the receiving field
KEYS = ("id", "text", "cars", "run", "head", "status", "train", "commit")
TEXT_MAX = 2000
# What the tollman says unasked about the yard and an old transplant: a note on the board, never a message (D9)
NOTES = ("yard-left", "yard-kept", "transplant-stale", "queue-leaver")  # queue-leaver: leavers.py (plan 0383)
NOTES_OF = {"tollman": NOTES, "farmer": ("note",)}  # the log's `record` kinds that become a `note` line


def utc(now: dt.datetime | None = None) -> str:
    """RFC 3339 UTC with `Z` and whole seconds; a time without a zone is this machine's local time."""
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def own(main: str, role: str = ROLE) -> str:
    """The role's field name, `<role>-<repo>`."""
    return mtm_scan.roles.slot_name(main, role)


def path(main: str, role: str = ROLE) -> Path:
    return mtm_scan.state_dir(main, role) / FILE


@contextlib.contextmanager
def locked(main: str, role: str = ROLE):
    """Writers and the prune take turns (flock on board.lock); the folder must exist: the board is the field's."""
    folder = path(main, role).parent
    if not folder.is_dir():
        raise FileNotFoundError(f"no state folder {folder}: the {role}'s field does not exist here")
    with (folder / LOCK).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield folder / FILE


def check(line: dict, role: str = ROLE) -> dict:
    """The line as the manifest's schema allows it, or ValueError saying what is wrong."""
    kind = line.get("kind")
    if kind not in KINDS_OF[role]:
        raise ValueError(f"no board kind {kind!r} (allowed: {', '.join(KINDS_OF[role])})")
    if not AT.match(line.get("at", "")):
        raise ValueError(f"`at` is not RFC 3339 UTC with Z: {line.get('at')!r}")
    for side in ("from", "to", "slot"):
        name = line.get(side)
        if not isinstance(name, str) or not FIELD.match(name) or NOT_FIELD.match(name):
            raise ValueError(f"`{side}` is no field name: {name!r} (never a pane id, session id or title)")
    for key in NEEDS[kind]:
        if not line.get(key):
            raise ValueError(f"a `{kind}` line needs `{key}`")
    if "cars" in line and not (isinstance(line["cars"], list) and all(isinstance(c, str) and FIELD.match(c)
                                                                       for c in line["cars"])):
        raise ValueError(f"`cars` are field names: {line['cars']!r}")
    if "id" in line and not ID.match(line["id"]):
        raise ValueError(f"`id` is no ack id (<slot>-<n>): {line['id']!r}")
    if kind == "ack" and line["status"] not in STATUSES:
        raise ValueError(f"an ack's status is one of {', '.join(STATUSES)}: {line['status']!r}")
    return line


def build(kind: str, frm: str, to: str, now: dt.datetime | None = None, slot: str | None = None,
          role: str = ROLE, **keys) -> dict:
    """A checked line; `slot` defaults to the foreman's side (the field that is not the role's)."""
    line = {"schema": SCHEMA, "at": utc(now), "kind": kind, "slot": slot or (to if kind in TO_SLOT else frm),
            "from": frm, "to": to,
            **{k: (v[:TEXT_MAX] if k == "text" else v) for k, v in keys.items() if k in KEYS and v not in (None, "")}}
    return check(line, role)


def write(file: Path, line: dict) -> None:
    """One line, one write under O_APPEND; the file is pruned first when it is over PRUNE_AT."""
    if file.exists() and file.stat().st_size > PRUNE_AT:
        prune(file)
    fd = os.open(file, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(line) + "\n").encode())
    finally:
        os.close(fd)


def prune(file: Path, keep: int | None = None) -> None:
    """Drop whole lines from the start until at most `keep` bytes are left (a temp file renamed over it)."""
    keep = PRUNE_TO if keep is None else keep
    rows = file.read_bytes().splitlines(keepends=True)
    size = sum(map(len, rows))
    while rows and size > keep:
        size -= len(rows.pop(0))
    tmp = file.with_name(file.name + ".tmp")
    tmp.write_bytes(b"".join(rows))
    os.replace(tmp, file)


def post(main: str, kind: str, frm: str, to: str, now: dt.datetime | None = None, role: str = ROLE, **keys) -> dict:
    """Append one line to the board; ValueError for a line the manifest's schema does not allow."""
    line = build(kind, frm, to, now, role=role, **keys)
    with locked(main, role) as file:
        write(file, line)
    return line


def lines(main: str, kind: str | None = None, last: int | None = None, role: str = ROLE) -> list[dict]:
    """The board's lines, oldest first; one that does not parse (a torn last line) is skipped."""
    f, out = path(main, role), []
    for text in f.read_text(errors="replace").splitlines() if f.exists() else []:
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("kind") and kind in (None, row["kind"]):
            out.append(row)
    return out[-last:] if last else out


def safely(main: str, what: str, fn, *args, **kw):
    """A hook's call: a failure is logged to the frame's log and swallowed, so a round goes on (D14); `role=` (the
    farmer's tick) goes on to `fn`."""
    try:
        return fn(main, *args, **kw)
    except Exception as e:  # noqa: BLE001  (any fault: the board must never stop a round)
        with contextlib.suppress(Exception):
            mtm_scan.log(main, {"kind": "board-failed", "slot": "-", "what": f"{what}: {e}"[:300], "by": "board"},
                         kw.get("role", ROLE))
        return None


def on_state(main: str, line: dict, train: dict | None = None) -> dict | None:
    """The train state's changes (train_state.append) as board lines: `formed` is `train`, then `landed`, `red` and
    `unhitched`; `started`, `retry` and `cleared` are no news to a foreman. `train` is the standing train."""
    kind, slot, name = line["kind"], line.get("slot", "-"), line.get("train")
    if kind == "formed":
        cars = [c["field"] for c in line.get("cars", [])]
        return post(main, "train", slot, "-", train=name, cars=cars, text=f"train {name} formed: {', '.join(cars)}")
    if kind == "landed":
        return post(main, "landed", slot, "-", train=name, cars=line.get("cars", []), run=line.get("run"),
                    commit=line.get("commit"), text=f"train {name} is in the barn")
    if kind == "red":
        cars = [c["field"] for c in (train or {}).get("cars", [])]
        return post(main, "red", slot, "-", train=name, cars=cars, run=line.get("run"), status=line.get("status"),
                    text=f"train {name} is red ({line.get('status')}): {line.get('why', '')}")
    if kind == "unhitched":
        return post(main, "unhitched", own(main), slot, train=name, text=line.get("why") or "unhitched")
    return None


def on_ready(main: str, tickets: list[dict]) -> list[dict]:
    """A `ready` line for every ticket marked ready that the board has not seen with this head: once per ticket
    and head, at the mark's own time (the queue's `ready.at`) when it is a UTC one."""
    me, out = own(main), []
    with locked(main) as file:
        seen = {(r.get("from"), r.get("head")) for r in lines(main, "ready")}
        for t in sorted(tickets, key=lambda t: t.get("position", 0)):
            mark, field = t.get("ready"), t.get("slot")
            if not mark or not mark.get("head") or field == me or (field, mark["head"]) in seen:
                continue
            at = mark.get("at", "")
            now = dt.datetime.fromisoformat(at.replace("Z", "+00:00")) if AT.match(at) else None
            try:
                line = build("ready", field, me, now, head=mark["head"],
                             text=f"{field} is ready to ride with {mark['head'][:12]}")
            except ValueError:
                continue  # a ticket whose name is no field's: not ours to post
            write(file, line)
            seen.add((field, mark["head"]))
            out.append(line)
    return out


def local_utc(at: str) -> dt.datetime | None:
    """The frame's `at` (this machine's local time, no zone) as an aware time."""
    try:
        return dt.datetime.fromisoformat(at).astimezone()
    except ValueError:
        return None


def sync(main: str, role: str = ROLE) -> list[dict]:
    """The frame's messages, acks and notes as lines, each once: an `ask-ack` entry of the frame's log is a
    `message` (the ack id is its `id`), an `ack` entry an `ack`, a `record` of a kind in the role's NOTES a `note`
    to its slot. Done under the lock, so two syncs never double a line; an entry the schema refuses (a slot that is
    no field name) is skipped, never a stopped sync."""
    me, out = own(main, role), []
    with locked(main, role) as file:
        have = lines(main, role=role)
        sent = {r.get("id") for r in have if r["kind"] == "message"}
        acked = {(r.get("id"), r.get("status"), r.get("at")) for r in have if r["kind"] == "ack"}
        noted = {(r.get("to"), r.get("text"), r.get("at")) for r in have if r["kind"] == "note"}
        for e in mtm_scan.entries(mtm_scan.state_dir(main, role) / "log.jsonl"):
            when, kind = local_utc(e["at"]), e["kind"]
            if when is None:
                continue
            try:
                if kind == "ask-ack" and e.get("id") and e["id"] not in sent:
                    line = build("message", me, e["slot"] or "-", when, role=role, id=e["id"],
                                 text=e.get("text") or e.get("what"))
                    sent.add(e["id"])
                elif kind == "ack" and e.get("id") and (e["id"], e["what"], utc(when)) not in acked:
                    line = build("ack", e["slot"] or "-", me, when, role=role, id=e["id"], status=e["what"],
                                 text=e.get("note"))
                    acked.add((e["id"], e["what"], line["at"]))
                elif e.get("do") == "record" and kind in NOTES_OF[role] and e.get("what") and \
                        (e.get("slot") or "-", e["what"][:TEXT_MAX], utc(when)) not in noted:
                    line = build("note", me, e.get("slot") or "-", when, role=role, text=e["what"])
                    noted.add((line["to"], line["text"], line["at"]))
                else:
                    continue
            except ValueError:
                continue
            write(file, line)
            out.append(line)
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    post_p, list_p = sub.add_parser("post"), sub.add_parser("list")
    sync_p = sub.add_parser("sync")
    post_p.add_argument("--kind", required=True)
    post_p.add_argument("--from", dest="frm", required=True)
    post_p.add_argument("--to", required=True)
    for key in ("text", "id", "run", "head", "status", "train", "commit"):
        post_p.add_argument(f"--{key}")
    post_p.add_argument("--cars", type=lambda s: [c for c in s.split(",") if c])
    list_p.add_argument("--kind")
    list_p.add_argument("--last", type=int)
    list_p.add_argument("--json", action="store_true")
    for x in (post_p, list_p, sync_p):
        x.add_argument("--repo", default=os.getcwd())
        x.add_argument("--role", default=ROLE, choices=ROLES)
    a = p.parse_args(argv)
    main_dir = mtm_scan.main_checkout(a.repo)
    try:
        if a.cmd == "post":
            keys = {k: getattr(a, k) for k in KEYS if hasattr(a, k)}
            print(json.dumps(post(main_dir, a.kind, a.frm, a.to, role=a.role, **keys)))
        elif a.cmd == "sync":
            print(f"{len(sync(main_dir, a.role))} lines posted")
        else:
            rows = lines(main_dir, a.kind, a.last, a.role)
            print(json.dumps(rows, indent=1) if a.json else "\n".join(
                f"{r['at']} {r['kind']:9} {r['from']} -> {r['to']}: {r.get('text', '')[:100]}" for r in rows)
                or "the board is empty")
    except (ValueError, OSError) as e:
        print(f"board.py: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
