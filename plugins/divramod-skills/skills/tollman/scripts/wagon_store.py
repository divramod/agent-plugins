#!/usr/bin/env python3
"""The tollman's wagon store: the facts of every wagon's train state (`wagons.jsonl` of the tollman's state folder).

The user, 2026-11-04: the table (wagons.py) and the tollman must read the same, always current
facts, persisted, never only in a handoff (hal2 plan 0604 D11, L225, L228). So the store keeps FACTS, never a
status; the status is computed from them and git on every read (wagon_status.py), so it cannot go stale or get stuck.

Facts (one JSON line each, schema 1, append-only, written under wagons.lock; `slot` is the wagon's field, as every
event-log line of a role folder names its subject; a line of before plan 0604 has `field` instead of `slot`: read as the
same, rewritten by `migrate`):
  order   {slot, id, at}            an acked order to the field's foreman (resolve, fix, merge)
  answer  {slot, id, ack, sha?, at}  the foreman's ack: started | done | refused, its sha if named
  need    {slot, sha, why, at}       a commit that must reach the carrier (the tollman's own hand)
  close   {slot, id, why, at}        an order that needs no answer any more (the tollman's own hand)

`ingest` re-reads ALL of log.jsonl each time (no cursor that could skip a line) and appends only
facts not stored yet (key: kind + id + ack + at), so it is idempotent, and a fact survives the
log's pruning and every ack's ageing (stale, void). Retention (stores-have-a-retention): past 1 MB the oldest
whole lines go, down to 512 KB, under the lock (`prune`); a fact of an older train is no longer read anyway.

The files are the state folder's (`folder(repo)`: mtm_scan.state_dir, FARMER_DIR honoured); every function takes the
store, log and train paths explicitly, the lock is `wagons.lock` beside the store.

Usage (each takes `--repo <dir>`, default the current directory):
  wagon_store.py need <field> <sha> --why <text>
  wagon_store.py answer <field> <order id> done|started|refused [--sha <sha>]
  wagon_store.py close <field> <order id> --why <text>
  wagon_store.py ingest
  wagon_store.py facts [<field>]
  wagon_store.py migrate                 old lines (`field`) rewritten with `slot`, once, by rename under the lock
"""
import argparse
import contextlib
import datetime
import fcntl
import json
import os
import re
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan

ROLE = "tollman"
STORE_NAME, LOCK_NAME = "wagons.jsonl", "wagons.lock"
MAX_BYTES, KEEP_BYTES = 1 << 20, 1 << 19
KINDS = ("order", "answer", "need", "close")
ACKS = ("started", "done", "refused")
SHA = re.compile(r"\b([0-9a-f]{7,40})\b")
# an ask that is a notice, no work for the foreman ("in the barn", "thanks, <sha> taken")
NOTICE = re.compile(r"^\s*(thanks\b|.{0,40}\bin the barn\b)", re.I)


def folder(repo) -> Path:
    """The tollman's state folder of `repo`'s farm."""
    return mtm_scan.state_dir(mtm_scan.main_checkout(str(repo)), ROLE)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextlib.contextmanager
def locked(store: Path):
    with store.with_name(LOCK_NAME).open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def facts(store: Path) -> list[dict]:
    path = store
    if not path.exists():
        return []
    out = []
    for raw in path.read_text().splitlines():
        try:
            r = json.loads(raw)
        except ValueError:
            continue  # a torn last line (crash mid-write) is skipped, never fatal
        slot = r.get("slot") or r.get("field") if isinstance(r, dict) else None
        if slot and r.get("kind") in KINDS:
            out.append({**r, "slot": slot, "field": slot})  # `field`: the readers' name for it
    return out


def key(r):
    return (r["kind"], str(r.get("id")), str(r.get("ack")), str(r.get("sha")), r.get("at"))


def _write(recs, store: Path):
    path = store
    if not recs:
        return
    torn = False
    if path.exists() and path.stat().st_size:
        with path.open("rb") as fh:
            fh.seek(-1, 2)
            torn = fh.read(1) != b"\n"
    with path.open("a") as fh:
        if torn:
            fh.write("\n")  # a crash mid-write left a torn line: never glue a fact onto it
        for r in recs:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
        fh.flush()
    prune(path)


def prune(path: Path) -> None:
    """Past MAX_BYTES the oldest whole lines go, down to KEEP_BYTES (by rename: a reader never sees half a file).
    The caller holds the lock."""
    if not path.exists() or path.stat().st_size <= MAX_BYTES:
        return
    lines = path.read_text().splitlines(keepends=True)
    keep, size = [], 0
    for line in reversed(lines):
        size += len(line.encode())
        if size > KEEP_BYTES:
            break
        keep.append(line)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text("".join(reversed(keep)))
    os.replace(tmp, path)


def add(kind, field, store: Path, **kw):
    rec = {"schema": 1, "kind": kind, "slot": str(field), "at": kw.pop("at", None) or now(),
           "by": kw.pop("by", "tollman")}
    rec.update({k: v for k, v in kw.items() if v is not None})
    with locked(store):
        _write([rec], store)
    return rec


def field_of(slot):
    m = re.match(r"^(\d{2}|farmer-[\w-]+|tollman-[\w-]+|yard|main)\b", str(slot or ""))
    return m.group(1) if m else None


def from_log(lines):
    """The order and answer facts in log.jsonl's lines (the frame's ask-ack and ack records)."""
    asks, out = {}, []
    for raw in lines:
        try:
            r = json.loads(raw)
        except ValueError:
            continue
        rid, at, kind = r.get("id"), r.get("at"), r.get("kind")
        if not rid or not at:
            continue
        if kind == "ask-ack":
            what = str(r.get("text") or r.get("what") or "")
            f = field_of(r.get("slot"))
            if not f or "train" not in what:
                continue
            body = what.split(":", 2)[-1][:160]
            if NOTICE.search(body):
                continue
            asks[rid] = f
            out.append({"schema": 1, "kind": "order", "slot": f, "id": rid, "at": at, "by": "ingest"})
        elif kind == "ack" and rid in asks:
            ack = str(r.get("what", "")).split()[0] if r.get("what") else ""
            if ack not in ACKS:
                continue
            m = SHA.search(f"{r.get('what', '')} {r.get('note', '')}") if ack == "done" else None
            rec = {"schema": 1, "kind": "answer", "slot": asks[rid], "id": rid, "ack": ack,
                   "at": at, "by": "ingest"}
            if m:
                rec["sha"] = m.group(1)
            out.append(rec)
    return out


def from_train(lines):
    """A `need` per commit the code merged into a carrier (train.jsonl's resolved and fixed lines)."""
    out = []
    for raw in lines:
        try:
            r = json.loads(raw)
        except ValueError:
            continue
        f, sha = field_of(r.get("field")), r.get("commit") or r.get("sha")
        if r.get("kind") in ("resolved", "fixed") and f and sha and r.get("at"):
            out.append({"schema": 1, "kind": "need", "slot": f, "sha": sha, "at": r["at"],
                        "id": r.get("id"), "why": f"train.jsonl {r['kind']}", "by": "ingest"})
    return out


def ingest(store: Path, log: Path, train: Path | None = None) -> int:
    """Append the facts of `log` (and of `train`, when given) that `store` lacks; how many were new."""
    new = from_log(log.read_text().splitlines()) if log.exists() else []
    if train is not None and train.exists():
        new += from_train(train.read_text().splitlines())
    with locked(store):
        have = {key(r) for r in facts(store)}
        todo = [r for r in new if key(r) not in have]
        _write(todo, store)
    return len(todo)


def migrate(store: Path) -> int:
    """Rewrite the lines of before plan 0604 (`field`, no `slot`) with `slot`; how many changed. Others stay as they are."""
    with locked(store):
        if not store.exists():
            return 0
        out, changed = [], 0
        for raw in store.read_text().splitlines():
            try:
                r = json.loads(raw)
            except ValueError:
                out.append(raw)
                continue
            if isinstance(r, dict) and "slot" not in r and r.get("field"):
                r = {**{k: v for k, v in r.items() if k != "field"}, "slot": r["field"]}
                raw, changed = json.dumps(r, sort_keys=True), changed + 1
            out.append(raw)
        if changed:
            tmp = store.with_name(f"{store.name}.{os.getpid()}.tmp")
            tmp.write_text("\n".join(out) + "\n")
            os.replace(tmp, store)
        return changed


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=os.getcwd())
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("need")
    n.add_argument("field")
    n.add_argument("sha")
    n.add_argument("--why", required=True)
    a = sub.add_parser("answer")
    a.add_argument("field")
    a.add_argument("id")
    a.add_argument("ack", choices=ACKS)
    a.add_argument("--sha")
    c = sub.add_parser("close")
    c.add_argument("field")
    c.add_argument("id")
    c.add_argument("--why", required=True)
    sub.add_parser("ingest")
    sub.add_parser("migrate")
    fa = sub.add_parser("facts")
    fa.add_argument("field", nargs="?")
    o = ap.parse_args(argv)
    home = folder(o.repo)
    store = home / STORE_NAME
    if o.cmd == "need":
        print(json.dumps(add("need", o.field, store, sha=o.sha, why=o.why)))
    elif o.cmd == "answer":
        print(json.dumps(add("answer", o.field, store, id=o.id, ack=o.ack, sha=o.sha)))
    elif o.cmd == "close":
        print(json.dumps(add("close", o.field, store, id=o.id, why=o.why)))
    elif o.cmd == "ingest":
        print(f"ingested {ingest(store, home / 'log.jsonl', home / 'train.jsonl')} new facts")
    elif o.cmd == "migrate":
        print(f"migrated {migrate(store)} lines")
    else:
        for r in facts(store):
            if o.field in (None, r["field"]):
                print(json.dumps(r, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
