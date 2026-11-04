"""The rewrite after the model's verdicts (plan 0592's D15): the model only judges, this writes. Given the verdicts
as JSON, it appends the plan's own ledger entries naming each outside decision with its link, marks a replaced own
entry `superseded` with `By:`, and rewrites the judged rows and their `steps/<n>.md`, before any code.

    {"entries": [{"id": "e1", "text": "<the decision taken over>", "why": "<why>", "link": "<link to the outside one>",
                  "supersedes": ["D2"]}],
     "steps": [{"step": "3", "verdict": "superseded", "by": "e1"},
               {"step": "4", "verdict": "changed", "by": "e1", "row": "<new Step cell>", "done_when": "<new cell>"},
               {"step": "5", "verdict": "valid"}]}

A superseded step's Status becomes `done: superseded by D<n>` (nothing left to do; the hitch rule reads `done`), a
changed one gets its new cells, a valid one stays. Each judged step's `steps/<n>.md` gets a dated line under
`## Notes`. Schema 1 plans only: a schema 2 plan's rows are its steps' files (`plan.py status`), refused here.
Everything is checked before the first write: refused verdicts change no file.
"""

import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import load  # noqa: E402

table = load("plan", "table")
VERDICTS = ("valid", "superseded", "changed")
HEADING = re.compile(r"^## D(\d+) · (.*)$")


class Refused(Exception):
    pass


def with_entries(text: str, entries: list[dict], today: str) -> tuple[str, list[str]]:
    """The ledger with each entry as the next `## D<n> · <today> · agent · in-force`, and their `D<n>` in order."""
    numbers = [int(m.group(1)) for line in text.splitlines() if (m := HEADING.match(line))]
    ids, n, blocks = [], max(numbers, default=0), []
    for entry in entries:
        n += 1
        ids.append(f"D{n}")
        why = (entry.get("why") or "").strip()
        link = (entry.get("link") or "").strip()
        blocks.append("\n".join([f"## D{n} · {today} · agent · in-force", "", f"**D:** {entry['text'].strip()}",
                                  f"**Why:** {why}{'; ' if why and link else ''}{'from ' + link if link else ''}"]))
    return (text.rstrip("\n") + "\n\n" + "\n\n".join(blocks) + "\n" if blocks else text), ids


def superseded(text: str, own: str, by: str) -> str:
    """The ledger with its entry `own` (`D2`) `superseded`, its `**By:**` naming `by`."""
    lines = text.split("\n")
    at = next((i for i, line in enumerate(lines) if (m := HEADING.match(line)) and f"D{m.group(1)}" == own), None)
    if at is None:
        raise Refused(f"no entry {own} in the ledger")
    lines[at] = " · ".join([*lines[at].split(" · ")[:-1], "superseded"])
    end = next((i for i in range(at + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    while end > at + 1 and not lines[end - 1].strip():
        end -= 1
    body = [i for i in range(at + 1, end) if lines[i].startswith("**By:**")]
    if body:
        lines[body[0]] = f"**By:** {by}"
    else:
        lines.insert(end, f"**By:** {by}")
    return "\n".join(lines)


def with_rows(text: str, steps: list[dict], ids: dict) -> str:
    """The plan with the judged rows' cells rewritten."""
    if re.search(r"(?m)^schema: *2\s*$", text.split("\n---", 1)[0]):
        raise Refused("a schema 2 plan: set its steps with plan.py status <ref> ... --why")
    lines = text.split("\n")
    found = table.header(lines)
    if found is None:
        raise Refused("no step table in the plan")
    at, cols = found
    rows = {cells[cols["#"]]: (i, cells) for i, cells in table.rows(lines, at)}
    for step in (s for s in steps if s["verdict"] != "valid"):
        if step["step"] not in rows:
            raise Refused(f"no row {step['step']} in the plan")
        i, cells = rows[step["step"]]
        if step["verdict"] == "superseded":
            cells[cols["status"]] = f"done: superseded by {by_of(step, ids)}"
        else:
            if step.get("row"):
                cells[cols["step"]] = step["row"]
            if step.get("done_when") and "done when" in cols:
                cells[cols["done when"]] = step["done_when"]
        lines[i] = table.join_row(cells) + table.eol(lines[i])
    return "\n".join(lines)


def by_of(step: dict, ids: dict) -> str:
    return ids.get(step.get("by"), step.get("by") or "a later decision")


def with_note(text: str, step: dict, by: str, today: str) -> str:
    """The step file with a dated line under its `## Notes` (the section added last when missing)."""
    what = "superseded" if step["verdict"] == "superseded" else "changed"
    line = f"- {today}: {what} by {by} (the consistency check of /continue)" + (
        f": {step['note']}" if step.get("note") else "")
    text = text.rstrip("\n")
    return text + ("\n" if "\n## Notes" in text else "\n\n## Notes\n") + "\n" + line + "\n"


def check(verdicts: dict) -> tuple[list[dict], list[dict]]:
    steps = [{**s, "step": str(s.get("step"))} for s in verdicts.get("steps") or []]
    bad = [s for s in steps if s.get("verdict") not in VERDICTS]
    if bad:
        raise Refused(f"unknown verdict {bad[0].get('verdict')!r} for step {bad[0]['step']}: one of {VERDICTS}")
    entries = verdicts.get("entries") or []
    if any(not (e.get("text") or "").strip() for e in entries):
        raise Refused("every entry needs its text")
    return steps, entries


def apply(plan: Path, ledger: Path, verdicts: dict, today: str | None = None) -> dict:
    today = today or dt.date.today().isoformat()
    steps, entries = check(verdicts)
    ledger_text, written = with_entries(ledger.read_text() if ledger.is_file() else "", entries, today)
    ids = {entry["id"]: d for entry, d in zip(entries, written) if entry.get("id")}
    for entry, d in zip(entries, written):
        for own in entry.get("supersedes") or []:
            ledger_text = superseded(ledger_text, own, d)
    plan_text = with_rows(plan.read_text(), steps, ids)
    notes = {}
    for step in (s for s in steps if s["verdict"] != "valid"):
        path = plan.parent / "steps" / f"{step['step']}.md"
        if path.is_file():
            notes[path] = with_note(notes.get(path) or path.read_text(), step, by_of(step, ids), today)
    ledger.write_text(ledger_text)
    plan.write_text(plan_text)
    for path, text in notes.items():
        path.write_text(text)
    return {"entries": written, "ids": ids, "rows": [s["step"] for s in steps if s["verdict"] != "valid"],
            "notes": [str(p) for p in notes], "valid": [s["step"] for s in steps if s["verdict"] == "valid"]}
