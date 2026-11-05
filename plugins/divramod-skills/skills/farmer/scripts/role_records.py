"""A role's records (hal2 plan 0611 step 2, design.md §1): what a role promised or has open, as facts.

`roles/<role>/records.jsonl` in the role's state folder is an append-only event log: an `open` line when a promise,
order or hand action happens, a `close` line when code sees it done. The open set is the fold of the log; a clear
loses none of it. The lib knows no role: a role registers its record types (`register`), each with the one closer
that may close it. Pattern of `train_state.py` and `board.prune`: one `os.write` under `O_APPEND`, a torn last line
skipped, the counter and the prune under `fcntl.flock`, the prune a temp file renamed over the log.

Line (schema 1): `{schema, at, kind: open|close, slot, record: "R<n>", type, what, by, event?, ...keys}` for an open,
`{schema, at, kind: close, slot, record, how, evidence, by}` for a close (`how`: the closer's name, `user`, or an extra
way the type allows). The key is `record`, not `id`: the role-folder envelope reserves `id` for `<slot>-<n>`; `lines` hands every row
out with `id` set to its record, so callers say `id` / `R<n>`. `records-number` holds the last number given, so a pruned record's number is never reused.
`list [--open] [--json] --role <role>` is the only verb: a record is written by the code that does the action.
"""

import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
import sys
from pathlib import Path
from typing import Callable, NamedTuple

import mtm_scan
import roletime

FILE, LOCK, NUMBER = "records.jsonl", "records.lock", "records-number"
SCHEMA = 1
KEEP_DAYS = 30
BYS = ("tollman", "code", "user")


class Kind(NamedTuple):
    """A record type of a role: `closer` the name of the code that closes it, `writers` the verbs that open it,
    `check(record, facts) -> evidence | None` the closer's reading of the code facts (None: still open), `hows`
    the further ways a close may name besides the closer and `user` (e.g. `void`)."""
    closer: str
    writers: tuple = ()
    check: Callable | None = None
    hows: tuple = ()


KINDS: dict[str, dict[str, Kind]] = {}
CONTRA: dict[str, dict[str, Callable[[dict, str], bool]]] = {}  # role -> type -> (record, sentence) -> goes against it


def register(role: str, kinds: dict[str, Kind]) -> None:
    """The role's record types; a second call adds to (or replaces) the same names."""
    KINDS.setdefault(role, {}).update(kinds)


def register_contra(role: str, rules: dict[str, Callable[[dict, str], bool]]) -> None:
    """For each record type of the role, `rule(record, sentence)`: True when the handoff sentence goes against that
    open record (handoff_records.py, hal2 plan 0611 step 7); a type without one has no such check."""
    CONTRA.setdefault(role, {}).update(rules)


def load(role: str) -> dict[str, Kind]:
    """The role's record types, its own `records_kinds.py` (in its skill's scripts/) imported once to register them,
    for a caller outside the role's folder (acks.py); {} for a role without one."""
    if role not in KINDS:
        import skillpath
        skillpath.load(role, "records_kinds", __file__)
    return KINDS.get(role, {})


def folder(main: str, role: str) -> Path:
    d = mtm_scan.state_dir(main, role)
    d.mkdir(parents=True, exist_ok=True)
    return d


def path(main: str, role: str) -> Path:
    return folder(main, role) / FILE


@contextlib.contextmanager
def locked(main: str, role: str):
    """The role's records lock (flock on records.lock): writers and the prune take turns."""
    with (folder(main, role) / LOCK).open("a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def lines(main: str, role: str) -> list[dict]:
    """The log's lines, oldest first; one that does not parse (a torn last line) is skipped."""
    f, out = path(main, role), []
    for text in f.read_text(errors="replace").splitlines() if f.exists() else []:
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("kind") in ("open", "close") and row.get("record"):
            out.append({**row, "id": row["record"]})
    return out


def fold(rows: list[dict]) -> dict[str, dict]:
    """`{id: the open line + closed: bool + the close line's how, evidence, closed_at, closed_by}`, in log order;
    a close with no open line (pruned) is ignored, the first close of an id wins."""
    out: dict[str, dict] = {}
    for row in rows:
        rid = row["id"]
        if row["kind"] == "open":
            out.setdefault(rid, {**row, "closed": False})
        elif rid in out and not out[rid]["closed"]:
            out[rid].update(closed=True, how=row.get("how"), evidence=row.get("evidence"),
                            closed_at=row.get("at"), closed_by=row.get("by"))
    return out


def open_(main: str, role: str) -> list[dict]:
    """The records still open, oldest first."""
    return [r for r in fold(lines(main, role)).values() if not r["closed"]]


def _append(f: Path, line: dict) -> None:
    fd = os.open(f, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(line) + "\n").encode())
    finally:
        os.close(fd)


def _next_number(main: str, role: str, rows: list[dict]) -> int:
    """The counter file, else (a log older than it) the highest number in the log; bumped by the caller's lock."""
    f = folder(main, role) / NUMBER
    try:
        last = int(f.read_text().strip() or 0)
    except (OSError, ValueError):
        last = 0
    last = max([last] + [int(r["id"][1:]) for r in rows if r["id"][1:].isdigit()])
    f.write_text(f"{last + 1}\n")
    return last + 1


def add(main: str, role: str, type: str, slot: str, what: str, by: str, event: dict | None = None,
        now: dt.datetime | None = None, **keys) -> dict:
    """Open a record and return its line. ValueError for a type the role did not register, a `by` not in BYS or an
    empty `what`; a key without a value is left out."""
    if type not in KINDS.get(role, {}):
        raise ValueError(f"role {role!r} has no record type {type!r}")
    if by not in BYS or not what.strip():
        raise ValueError("a record needs `what` and a `by` of tollman, code or user")
    with locked(main, role):
        rid = f"R{_next_number(main, role, lines(main, role))}"
        line = {"schema": SCHEMA, "at": roletime.now(now), "kind": "open", "slot": slot or "-", "record": rid,
                "type": type, "what": what.strip(), "by": by,
                **{k: v for k, v in {"event": event, **keys}.items() if v is not None}}
        _append(path(main, role), line)
    return {**line, "id": rid}


def close(main: str, role: str, id: str, how: str, evidence: str, by: str = "code",
          now: dt.datetime | None = None) -> bool:
    """Close the open record `id`: True when this call closed it, False when it is not open (idempotent). ValueError
    for a `how` that is neither the type's closer, `user` nor one of its `hows`, or empty evidence."""
    with locked(main, role):
        rec = fold(lines(main, role)).get(id)
        if rec is None or rec["closed"]:
            return False
        kind = KINDS.get(role, {}).get(rec["type"])
        if kind is None or how not in (kind.closer, "user", *kind.hows):
            raise ValueError(f"{id} ({rec['type']}) is closed by {kind.closer if kind else '?'} or user, not {how!r}")
        if not str(evidence).strip() or by not in BYS:
            raise ValueError("a close needs the evidence it read and a `by`")
        _append(path(main, role), {"schema": SCHEMA, "at": roletime.now(now), "kind": "close", "slot": rec["slot"],
                                   "record": id, "how": how, "evidence": str(evidence), "by": by})
    return True


def sweep(main: str, role: str, now: dt.datetime | None = None, facts: dict | None = None) -> list[str]:
    """Close each open record whose type's `check(record, facts)` returns evidence, or `(how, evidence)` for one of
    the type's `hows` (the question's `void`). Returns one line per close and per closer that raised (that record
    stays open): `R3 closed by x: ...` / `R4 closer failed: ...`. The closers take what they need lazily from
    `facts`, a dict they fill once per sweep (`main` set here)."""
    facts, out = {} if facts is None else facts, []
    facts.setdefault("main", main)
    for rec in open_(main, role):
        kind = KINDS.get(role, {}).get(rec["type"])
        if kind is None or kind.check is None:
            continue
        try:
            got = kind.check(rec, facts)
            how, evidence = got if isinstance(got, tuple) else (kind.closer, got)
            if evidence and close(main, role, rec["id"], how, str(evidence), "code", now):
                out.append(f"{rec['id']} closed by {how}: {evidence}")
        except Exception as e:  # noqa: BLE001  (one closer's fault leaves its record open, never stops the round)
            out.append(f"{rec['id']} closer failed: {e}")
    return out


def prune(main: str, role: str, now: dt.datetime | None = None, days: int = KEEP_DAYS) -> int:
    """Drop the records closed more than `days` days ago (their open and close lines); an open record, a recently
    closed one and every line this lib does not know stay. A temp file renamed over the log, under the lock.
    Returns the number of records dropped."""
    f = path(main, role)
    if not f.exists():
        return 0
    cutoff = (now or roletime.utcnow()) - dt.timedelta(days=days)
    with locked(main, role):
        folded = fold(lines(main, role))
        old = {i for i, r in folded.items() if r["closed"] and (roletime.parse(r["closed_at"]) or cutoff) < cutoff}
        if not old:
            return 0
        keep = []
        for text in f.read_text(errors="replace").splitlines():
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not (isinstance(row, dict) and row.get("record") in old and row.get("kind") in ("open", "close")):
                keep.append(text + "\n")
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text("".join(keep))
        os.replace(tmp, f)
    return len(old)


def show(rec: dict) -> str:
    done = f" [closed by {rec['how']}]" if rec["closed"] else ""
    return f"{rec['id']} {rec['type']} {rec['slot']}: {rec['what']} ({rec['by']}, {rec['at']}){done}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="role_records.py", description="List a role's records (read-only; code writes them).")
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="the records, oldest first")
    ls.add_argument("--role", required=True)
    ls.add_argument("--open", action="store_true", help="only the open ones")
    ls.add_argument("--json", action="store_true")
    ls.add_argument("--repo", default=os.getcwd())
    args = p.parse_args(argv)
    main_dir = mtm_scan.main_checkout(args.repo)
    recs = open_(main_dir, args.role) if args.open else list(fold(lines(main_dir, args.role)).values())
    print(json.dumps(recs, indent=2) if args.json else "\n".join(map(show, recs)) or "no records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
