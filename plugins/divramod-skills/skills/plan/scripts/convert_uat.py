"""An old plan's `uat.md` and `uat-results.jsonl` into its `subplans/99-uat/` (hal2 plan 0376, design §7, A7, A12,
D15): the sub-plan takes the shotfile, `landed` and `Before you start:`; each `## U<n>` becomes a UAT step in order
(its `check` kept, the Priority, Tags and Kind lines as keys, the rest verbatim); each result line becomes a
`## Verdicts` line of its check's step in time order, the newest setting `verdict` and `status`. An archived uat.md
drops the checks without a verdict (a step with one follows it: rule uat-verdict-status). Both old files go. A plan
without a uat.md gets an empty 99-uat, `done`.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import convert_text as text
import envelope
import folder as plan_folder
import shape
import shape_names as sn
import shape_new
from shape_docs import Subplan, UatStep
from shape_names import ShapeError

UAT, RESULTS = "uat.md", "uat-results.jsonl"
HOME = f"{shape.SUBPLANS}/{sn.UAT_FOLDER}"
LEGACY_KEYS = re.compile(r"^(Plan|Created|Shotfile|Landed|Status):\s*(.*)$")
CHECK = re.compile(r"^(U\d+)\b\s*[:.\-—]?\s*(.*)$")
FIELD = re.compile(r"^(Priority|Tags|Kind):\s*(.*)$")
COMMENT = re.compile(r"<!-- Checks only a human can do.*?-->\n?", re.S)
BEFORE = re.compile(r"^Before you start:\s*(.*?)(?:\n\s*\n|\Z)", re.M | re.S)


def paragraph(body: str, name: str) -> str:
    found = re.search(rf"^{name}:\s*(.*?)(?:\n\s*\n|\Z)", body, re.M | re.S)
    return " ".join(found.group(1).split()) if found else ""


def head_of(head: str) -> tuple[dict, str, str]:
    """A uat.md's text before its first check: the legacy key lines, `Before you start:` and the other prose."""
    keys, kept = {}, []
    for line in COMMENT.sub("", head).splitlines():
        found = LEGACY_KEYS.match(line)
        if found:
            keys[found.group(1).lower()] = found.group(2).strip()
        elif not line.startswith("# "):
            kept.append(line)
    prose = "\n".join(kept)
    before = BEFORE.search(prose)
    if before:
        prose = prose[:before.start()] + prose[before.end():]
    return keys, before.group(1).strip() if before else "", prose.strip()


def check_of(title: str, part: str) -> dict | None:
    """One `## U<n> <title>` section: its id, title, keys and the rest of its body."""
    found = CHECK.match(title)
    if not found:
        return None
    keys, rest = {}, []
    for line in part.splitlines():
        field = FIELD.match(line)
        if field and field.group(1).lower() not in keys:
            keys[field.group(1).lower()] = field.group(2).strip()
            if field.group(1) == "Kind" and field.group(2).strip() not in ("scripted", "explore"):
                rest.append(line)
        else:
            rest.append(line)
    priority = keys.get("priority", "").split()[0] if keys.get("priority") else ""
    return {"check": found.group(1), "title": text.one_line(found.group(2) or found.group(1)),
            "priority": priority if priority in ("p1", "p2", "p3") else "p2",
            "kind": keys.get("kind") if keys.get("kind") in ("scripted", "explore") else "scripted",
            "tags": [t.strip() for t in keys.get("tags", "").split(",") if t.strip()],
            "body": text.strip_blank("\n".join(rest))}


def when(record: dict):
    try:
        return dt.datetime.fromisoformat(str(record.get("at", ""))).timestamp()
    except ValueError:
        return 0.0


def verdict_line(record: dict) -> str:
    """`- <at> · <verdict> · by <by> · at <commit> · v <uat version>` (then step, duration, evidence) `— "<note>"`."""
    parts = [str(record.get("at", "")), record["status"], f"by {record.get('by') or 'cli'}"]
    if record.get("commit"):
        parts.append(f"at {str(record['commit'])[:7]}")
    if record.get("uat_version"):
        parts.append(f"v {str(record['uat_version']).split(':')[-1][:8]}")
    if record.get("step") is not None:
        parts.append(f"step {record['step']}")
    if record.get("duration") is not None:
        parts.append(f"{record['duration']}s")
    evidence = record.get("evidence") or []
    if evidence:
        parts.append("evidence " + ", ".join(Path(str(e)).name for e in (evidence if isinstance(evidence, list)
                                                                         else [evidence])))
    note = text.one_line(record.get("note") or "").replace('"', "'")
    return "- " + " · ".join(parts) + (f' — "{note}"' if note else "")


def results(folder: Path, checks: set[str]) -> dict[str, list[dict]]:
    """uat-results.jsonl by check, each in time order; an error for a line naming no check of uat.md."""
    path, out = folder / RESULTS, {}
    if not path.is_file():
        return out
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("check") not in checks:
            raise ShapeError(f"{RESULTS} line {n} names check `{record.get('check')}`, which {UAT} has not")
        sn.verdict_status(str(record.get("status")))
        out.setdefault(record["check"], []).append(record)
    return {check: sorted(found, key=when) for check, found in out.items()}


def step_of(plan: int, number: int, check: dict, verdicts: list[dict], archived: bool) -> UatStep:
    here = f"{HOME}/steps"
    body = f"\n# Step {number:02d}: {check['title']}\n\n{text.rewrite_links(check['body'], '', here, {})}\n"
    verdict = verdicts[-1]["status"] if verdicts else None
    if verdicts:
        body += "\n## Verdicts\n\n" + "".join(verdict_line(r) + "\n" for r in verdicts)
    status = sn.verdict_status(verdict) if verdict else ("dropped" if archived else "open")
    if archived and not verdict:
        body = body.replace("\n\n", f"\n\nDropped: archived (its uat.md's status).\n\n", 1)
    expected = paragraph(check["body"], "Expected")
    return UatStep(title=check["title"], description=text.cut(plan_folder.describe(expected, check["title"])),
                   status=status, plan=plan, check=check["check"], priority=check["priority"], kind=check["kind"],
                   tags=check["tags"], verdict=verdict, body=body)


def subplan_of(plan: int, meta: dict, before: str, notes: str, title: str) -> Subplan:
    body = "\n# Sub-plan 99: uat\n\n## Goal\n\nThe user confirms by hand on the default branch what the plan delivered.\n"
    if before:
        body += f"\n## Before you start\n\n{text.rewrite_links(before, '', HOME, {})}\n"
    body += "\n## Done when\n\nEvery check has a verdict.\n"
    if notes:
        body += f"\n## Notes\n\n{text.rewrite_links(notes, '', HOME, {})}\n"
    landed = str(meta.get("landed") or "")[:10]
    return Subplan(title="uat", description=shape_new.UAT_DELIVERABLE, status="open", plan=plan,
                   shotfile=str(meta.get("shotfile") or "") or shape_new.feature(title),
                   landed=landed if re.fullmatch(r"\d{4}-\d\d-\d\d", landed) else None, body=body)


def empty(folder: Path, plan: int, title: str) -> None:
    uat = Subplan(title="uat", description=shape_new.UAT_DELIVERABLE, status="done", plan=plan,
                  shotfile=shape_new.feature(title), body=shape_new.UAT_BODY)
    shape_new.write_subplan(folder, sn.UAT_NUMBER, "uat", uat)


def convert(folder: Path, plan: int, title: str) -> dict:
    """Write `subplans/99-uat/` from uat.md and its results (or empty); remove both. Returns {checks, verdicts}."""
    path = folder / UAT
    if not path.is_file():
        empty(folder, plan, title)
        (folder / RESULTS).unlink(missing_ok=True)
        return {"checks": 0, "verdicts": 0}
    front, body = envelope.split(path.read_text())
    meta = envelope.parse(front) if front else {}
    head, parts = text.sections(body)
    keys, before, prose = head_of(head)
    meta = {**keys, **meta}
    checks = [c for t, p in parts if (c := check_of(t, p))]
    others = [f"### {t}\n\n{text.strip_blank(p)}" for t, p in parts if not CHECK.match(t)]
    found = results(folder, {c["check"] for c in checks})
    archived = str(meta.get("status", "")).lower() == "archived"
    sub = subplan_of(plan, meta, before, "\n\n".join([prose, *others]).strip(), title)
    sub_dir = shape_new.write_subplan(folder, sn.UAT_NUMBER, "uat", sub).parent
    for n, check in enumerate(checks, 1):
        step = step_of(plan, n, check, found.get(check["check"], []), archived)
        out = sub_dir / "steps" / sn.step_file(n, len(checks) > 99)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(step.render())
    path.unlink()
    (folder / RESULTS).unlink(missing_ok=True)
    return {"checks": len(checks), "verdicts": sum(len(v) for v in found.values())}
