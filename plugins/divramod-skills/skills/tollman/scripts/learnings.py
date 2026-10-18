#!/usr/bin/env python3
"""A role's learnings file (hal2 plan 0313 step 4, decision D8): `roles/<role>/learnings.md`, the runtime file in which
a role writes one entry after each red train, error or by-hand fix. Generic: the role folder is the argument, so the
farmer reuses it with `roles/farmer/learnings.md`. Stdlib only.

An entry is a section of the file:

    ## L<n> · <UTC date time> · <case slug>

    **Case:** what happened
    **Cause:** why
    **Rule:** from now on ...
    **Code change:** y|n
    **Start:** <UTC date time>     when the rule took effect (the writer's time unless given)
    **Metric:** <name>             the metrics.py number it should move (verdicts.py's METRICS), named by the session
    **Taken:** -|<date> <plan>

The daily duty `learn` (verdicts.py, plan 0313 step 7) adds `**Status:** kept|dropped|revise` and `**Verdict:**`
once the rule's 7 days after its start are measured, and `**Handed:**` when a revise or drop went to a foreman; a
dropped rule is no longer applied. Further `**Key:** value` lines are kept as they are and returned in
`Entry.fields`. The parser also reads the older hand-written shape (`## <date> · <title>`, bullets like
`- **What**: ...`, `- **Code**: yes ...`): `What` is the case, `Code` starts with y or not, a missing `Taken` is
untaken; entries are numbered by position. A heading without a `Case` or `Rule` field (a dated section of
loose bullets) is no entry.

    learnings.py [--role <name> | --dir <folder>] add --case ... --cause ... --rule ... --code y|n [--slug ...]
                 [--metric <name>] [--start <UTC time>] [--field Key=Value ...]
    learnings.py ... untaken [--code y] [--json]   the entries not taken yet
    learnings.py ... mark-taken <n> [<n> ...] [--plan <plan>]
    learnings.py ... rules                          one line per entry: its number, slug and rule (what act reads)
"""

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

FILE = "learnings.md"
LOCK = "learnings.lock"  # declared by the manifest's `*.lock`
ALIASES = {"what": "case", "code": "code change"}
FIELD = re.compile(r"^\s*(?:[-*]\s+)?\*\*([A-Za-z][A-Za-z ]*?)(?:\*\*(?:\s*\([^)]*\))?:|:\*\*)\s*(.*)$")
HEAD = re.compile(r"^## (.+)$")
DATE = re.compile(r"^\d{4}-\d\d-\d\d")
NUMBER = re.compile(r"^L(\d+)$")


@dataclass
class Entry:
    n: int
    at: str
    slug: str
    fields: dict = field(default_factory=dict)  # lower-case key -> text, in file order
    start: int = 0  # first line (the heading) in the file
    end: int = 0  # one past the last line

    @property
    def case(self):
        return self.fields.get("case", "")

    @property
    def rule(self):
        return self.fields.get("rule", "")

    @property
    def code(self):
        """`y` when the entry wants a code change, else `n`."""
        return "y" if self.fields.get("code change", "").strip().lower().startswith("y") else "n"

    @property
    def status(self):
        """`kept`, `dropped`, `revise` once judged, else ""."""
        return self.fields.get("status", "").strip().split(" ")[0].lower()

    @property
    def taken(self):
        t = self.fields.get("taken", "").strip()
        return "" if t in ("", "-") else t

    def as_dict(self):
        return {"n": self.n, "at": self.at, "slug": self.slug, "code": self.code, "taken": self.taken,
                "fields": self.fields}


def folder(role="tollman", directory=None):
    if directory:
        return Path(directory)
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    return Path(top or ".") / "roles" / role


def _heading(text):
    """(n or None, at, slug) of an entry heading, else None (a section that is no entry)."""
    parts = [p.strip() for p in text.split(" · ")]
    m = NUMBER.match(parts[0])
    if m and len(parts) == 3:
        return int(m.group(1)), parts[1], parts[2]
    if DATE.match(parts[0]) and len(parts) >= 2:
        return None, parts[0], " · ".join(parts[1:])
    return None


def parse(text):
    """The entries of a learnings file, in file order."""
    lines = text.splitlines()
    entries, cur, last = [], None, None
    for i, line in enumerate(lines):
        h = HEAD.match(line)
        if h:
            if cur:
                cur.end = i
            head = _heading(h.group(1))
            cur, last = None, None
            if head:
                n, at, slug = head
                cur = Entry(n or 0, at, slug, start=i)
                entries.append(cur)
            continue
        if not cur:
            continue
        m = FIELD.match(line)
        if m:
            key = m.group(1).strip().lower()
            last = ALIASES.get(key, key)
            cur.fields[last] = m.group(2).strip()
        elif line.strip() and last and line[:1] in " \t":  # a continuation line
            cur.fields[last] = (cur.fields[last] + " " + line.strip()).strip()
    if cur:
        cur.end = len(lines)
    # a dated section of loose bullets is no entry
    entries = [e for e in entries if "case" in e.fields or "rule" in e.fields]
    used = 0
    for e in entries:  # a legacy entry takes its position, an explicit number wins
        used = e.n or used + 1
        e.n = used
    return entries


def read(directory):
    p = directory / FILE
    return parse(p.read_text()) if p.is_file() else []


@contextmanager
def locked(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / LOCK, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def _write(path, text):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".learnings-")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def _slug(text):
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    return "-".join(words[:6]) or "entry"


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%MZ")


def _envelope(role):
    return (f"---\ntype: Ledger\nschema: 1\nrole: {role}\ntitle: {role} learnings\n"
            "description: One entry per red train, error or by-hand fix; act reads it first, a daily duty acts on it.\n"
            f"status: current\n---\n\n# {role} learnings\n")


def _line(text):
    return " ".join(str(text).split())  # one line: an entry's field never holds a heading or a second field


def add(directory, case, cause, rule, code="n", slug=None, at=None, extra=(), role=None, metric=None, start=None):
    """Append an entry, return it. `Start` is `start`, else the entry's time; `Metric` when named; `extra`: further
    (Key, value) pairs written after them."""
    if code not in ("y", "n"):
        raise ValueError("code is y or n")
    with locked(directory):
        path = directory / FILE
        text = path.read_text() if path.is_file() else _envelope(role or directory.name)
        n = max([e.n for e in parse(text)] + [0]) + 1
        at = at or _now()
        given = {k.strip().lower() for k, _ in extra}
        rows = [("Case", case), ("Cause", cause), ("Rule", rule), ("Code change", code)]
        rows += [("Start", start or at)] if "start" not in given else []
        rows += [("Metric", metric)] if metric and "metric" not in given else []
        rows += [(k, v) for k, v in extra] + [("Taken", "-")]
        block = f"## L{n} · {at} · {_slug(slug or case)}\n\n" + "\n".join(
            f"**{k}:** {_line(v)}" for k, v in rows) + "\n"
        _write(path, text.rstrip("\n") + "\n\n" + block)
        return _entry(block, n)


def _entry(block, n):
    e = parse(block)[0]
    e.n = n
    return e


def untaken(directory, code=None):
    return [e for e in read(directory) if not e.taken and (code is None or e.code == code)]


def mark_taken(directory, numbers, plan="-", today=None):
    """Set `Taken: <date> <plan>` on the entries, return the numbers marked (unknown ones are not)."""
    stamp = f"{today or dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')} {plan}"
    return set_fields(directory, {n: {"Taken": stamp} for n in numbers})


def set_fields(directory, updates):
    """Set `**Key:** value` lines on entries, `updates` {n: {Key: value}}: an existing line of the key is replaced
    in place, else the line is added at the entry's end. Returns the numbers changed (unknown ones are not)."""
    with locked(directory):
        path = directory / FILE
        if not path.is_file():
            return []
        text = path.read_text()
        lines = text.splitlines()
        done = []
        for e in sorted(parse(text), key=lambda e: -e.start):  # from the bottom, so line numbers hold
            if e.n not in updates:
                continue
            for key, value in updates[e.n].items():
                _set_line(lines, e, key, _line(value))
            done.append(e.n)
        _write(path, "\n".join(lines) + "\n")
        return sorted(done)


def _set_line(lines, e, key, value):
    at = next((i for i in range(e.start + 1, e.end) if _key_of(lines[i]) == key.lower()), None)
    if at is not None:
        lines[at] = re.sub(r"^(\s*(?:[-*]\s+)?)\*\*.*$", lambda m: f"{m.group(1)}**{key}:** {value}", lines[at])
        return
    end = e.end
    while end > e.start + 1 and not lines[end - 1].strip():
        end -= 1
    lines.insert(end, f"**{key}:** {value}")
    e.end += 1


def _key_of(line):
    m = FIELD.match(line)
    return m.group(1).strip().lower() if m else None


def rules_text(directory):
    def tags(e):
        return (" [taken]" if e.taken else "") + (" [dropped: not applied]" if e.status == "dropped" else "")
    return "\n".join(f"L{e.n} {e.slug}{tags(e)}: {e.rule or e.case}" for e in read(directory))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--role", default="tollman")
    ap.add_argument("--dir", help="the role folder (default: roles/<role> of this checkout)")
    sub = ap.add_subparsers(dest="verb", required=True)
    a = sub.add_parser("add")
    for k in ("case", "cause", "rule"):
        a.add_argument(f"--{k}", required=True)
    a.add_argument("--code", choices=("y", "n"), default="n")
    a.add_argument("--slug")
    a.add_argument("--at", help="UTC date time, default now")
    a.add_argument("--metric", help="the metric the rule should move (verdicts.py's METRICS)")
    a.add_argument("--start", help="when the rule took effect, UTC; default the entry's time")
    a.add_argument("--field", action="append", default=[], metavar="KEY=VALUE")
    u = sub.add_parser("untaken")
    u.add_argument("--code", choices=("y", "n"))
    u.add_argument("--json", action="store_true")
    m = sub.add_parser("mark-taken")
    m.add_argument("numbers", nargs="+", type=int)
    m.add_argument("--plan", default="-")
    sub.add_parser("rules")
    args = ap.parse_args(argv)
    d = folder(args.role, args.dir)
    if args.verb == "add":
        extra = [tuple(f.split("=", 1)) for f in args.field if "=" in f]
        e = add(d, args.case, args.cause, args.rule, args.code, args.slug, args.at, extra, args.role, args.metric,
                args.start)
        print(f"L{e.n} {e.slug}")
    elif args.verb == "untaken":
        found = untaken(d, args.code)
        if args.json:
            print(json.dumps([e.as_dict() for e in found], indent=1))
        else:
            for e in found:
                print(f"L{e.n} · {e.at} · {e.slug} · code {e.code}: {e.rule or e.case}")
    elif args.verb == "mark-taken":
        done = mark_taken(d, set(args.numbers), args.plan)
        print("taken: " + (", ".join(f"L{n}" for n in done) or "none"))
        return 0 if done else 1
    else:
        print(rules_text(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
