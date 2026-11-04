"""lessons.py: the plan skill's lessons, `plan.py lesson add <class> <text> [--plan <NNNN>]` and `lesson list [--json]`
(hal2 plan 0514 step 11, D11).

`references/lessons.md` holds one entry per lesson: a `## <class>` heading and the lines `- date:`, `- plan:`,
`- lesson:`. The farmer finds a class by its heading; grill-plan's Auto round reads `lesson list`.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

SCHEMA = 1
FILE = Path(__file__).resolve().parent.parent / "references" / "lessons.md"
HEAD = re.compile(r"^## (\S+)\s*$")
FIELD = re.compile(r"^- (date|plan|lesson):\s*(.*)$")
CLASS = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class LessonError(Exception):
    pass


def entries(path: Path = FILE) -> list[dict]:
    out: list[dict] = []
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if m := HEAD.match(line):
            out.append({"class": m.group(1), "date": "", "plan": "", "lesson": ""})
        elif out and (m := FIELD.match(line)):
            out[-1][m.group(1)] = m.group(2).strip()
    return out


def add(kind: str, text: str, plan: str = "", path: Path = FILE, today: str | None = None) -> dict:
    text = " ".join(text.split())
    if not CLASS.match(kind):
        raise LessonError(f"class {kind!r}: use lower-case words joined by '-'")
    if not text:
        raise LessonError("the lesson text is empty")
    if any(e["class"] == kind and e["lesson"] == text for e in entries(path)):
        raise LessonError(f"class {kind}: this lesson is already written")
    entry = {"class": kind, "date": today or date.today().isoformat(), "plan": plan, "lesson": text}
    body = path.read_text() if path.exists() else "# Lessons\n"
    body = body.rstrip("\n") + (f"\n\n## {kind}\n- date: {entry['date']}\n- plan: {plan}\n- lesson: {text}\n")
    path.write_text(body)
    return entry


def show(path: Path = FILE, as_json: bool = False) -> str:
    found = entries(path)
    if as_json:
        return json.dumps({"schema": SCHEMA, "lessons": found}, ensure_ascii=False)
    return "\n".join(f"{e['class']} ({e['date']}, plan {e['plan'] or '-'}): {e['lesson']}" for e in found) or "no lessons"


def run(args) -> int:
    """`plan.py lesson ...`: args.action add|list."""
    try:
        if args.action == "add":
            e = add(args.cls, " ".join(args.text), args.plan or "")
            print(f"lesson written: {e['class']}")
        else:
            print(show(as_json=args.json))
    except LessonError as error:
        print(f"plan.py: {error}", file=sys.stderr)
        return 2
    return 0
