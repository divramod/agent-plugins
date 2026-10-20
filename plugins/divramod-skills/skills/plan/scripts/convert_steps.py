"""The step table of an old plan into the one plan shape (hal2 plan 0376, design §7, D16): one work sub-plan
`01-<the plan's slug, at most four words>` holding every row as `steps/step-NN.md` in row order. A row's existing
`steps/<id>.md` moves into it: its heading renumbered, its `Size:` line dropped, sections the Plan Step kind has not
(`Needs and touches`, `Your rules`, ...) folded into its Notes, its relative links re-pointed. A parallel plan's
Needs become waves (one above the deepest need, one more where a wave would share a resource), Touches `touches`, the
sub-plan `schedule: waves`; Who is dropped.
"""
from __future__ import annotations

import re
from pathlib import Path

import convert_text as text
import envelope
import folder as plan_folder
import parallel
import shape
import shape_names as sn
import table
from shape_docs import PlanStep, Subplan

KNOWN = ("Task", "Approach", "Done when", "Notes", "Result")
DROPPED = ("moved", "dropped", "later", "draft", "absorbed")
COMMENT = re.compile(r"<!-- Short and concise \(hal2's record plans-short-and-concise\).*?-->\n?", re.S)
SIZE_LINE = re.compile(r"^Size: [^\n]*\n?", re.M)
MARKERS = ("research", "masterplan")


def subplan_slug(plan_slug: str) -> str:
    """`0376-one-plan-shape` -> `one-plan-shape`: at most four words, the markers `research`/`masterplan` not
    counted."""
    words = [w for w in plan_slug[5:].split("-") if w]
    while words and words[0] in MARKERS and len(words) > 1:
        words = words[1:]
    return "-".join(words[:4]) or "steps"


def map_status(cell: str) -> tuple[str, str | None, bool]:
    """(status, why, reported) of an old Status cell: `done…` done (the rest the why); blank open; next, running;
    `blocked <why>`; moved, dropped, later, draft, absorbed: dropped (the cell the why); anything else open,
    reported."""
    raw = cell.strip()
    low = raw.lower().strip("*_ ")
    rest = lambda word: text.one_line(raw.strip("*_ ")[len(word):].strip(" :;,-—*_")) or None  # noqa: E731
    if not low or low == "open":
        return "open", None, False
    if low.startswith("done"):
        return "done", rest("done"), False
    for word in ("next", "running"):
        if low.startswith(word):
            return word, None, False
    if low.startswith("blocked"):
        return "blocked", rest("blocked"), False
    if low.startswith(DROPPED):
        return "dropped", text.one_line(raw), False
    return "open", None, True


def rows_of(plan_text: str) -> tuple[dict[str, int], list[list[str]]]:
    """The step table's columns and rows; none without a table."""
    lines = plan_text.splitlines()
    found = table.header(lines)
    if found is None:
        return {}, []
    at, cols = found
    return cols, [cells for _, cells in table.rows(lines, at) if len(cells) > cols["status"]]


def waves(steps: list[dict]) -> None:
    """Each parallel row's wave: one above the deepest wave it needs, one more while a row of that wave shares a
    resource that is no machine's (`@`)."""
    by_id = {s["id"]: s for s in steps}
    placed: list[dict] = []

    def wave(step: dict, seen: frozenset) -> int:
        if "wave" in step:
            return step["wave"]
        needs = [by_id[n] for n in step["needs"] if n in by_id and n not in seen]
        w = 1 + max((wave(n, seen | {step["id"]}) for n in needs), default=0)
        while any(p["wave"] == w and set(t for t in step["touches"] if not t.startswith("@")) & set(p["touches"])
                  for p in placed):
            w += 1
        step["wave"] = w
        placed.append(step)
        return w

    for step in steps:
        wave(step, frozenset())


def read_rows(plan_text: str, run: list[str]) -> tuple[list[dict], bool, list[str]]:
    """The rows as step dicts (id, title, done_when, status, why, sizing, needs, touches, wave), whether the plan is
    parallel, and the notes (unknown statuses)."""
    cols, rows = rows_of(plan_text)
    cell = lambda cells, name: cells[cols[name]].strip() if name in cols and cols[name] < len(cells) else ""  # noqa
    steps, notes, par = [], [], parallel.is_parallel(cols)
    for n, cells in enumerate(rows, 1):
        status, why, odd = map_status(cell(cells, "status"))
        if odd:
            notes.append(f"row {cell(cells, '#')}: status `{cell(cells, 'status')}` is none known: open")
        step = {"id": cell(cells, "#"), "number": n, "title": cell(cells, "step") or f"Step {n}",
                "done_when": cell(cells, "done when"), "status": status, "why": why,
                "model": cell(cells, "model") or run[0] or None, "effort": cell(cells, "effort") or run[1] or None,
                "window": cell(cells, "window") or run[2] or None, "size": cell(cells, "size") or None,
                "touches": parallel.parse_touches(cell(cells, "touches"), cell(cells, "step")) if par else []}
        step["needs"] = parallel.parse_needs(cell(cells, "needs"))[0] if par else []
        steps.append(step)
    if par:
        waves(steps)
    else:
        for step in steps:
            step["wave"] = step["number"]
    return steps, par, notes


def heading_rest(head: str, title: str) -> str:
    line = next((l for l in head.splitlines() if l.startswith("# ")), "")
    found = re.match(r"^# Step [^:]+:\s*(.*)$", line)
    return found.group(1).strip() if found and found.group(1).strip() else text.one_line(title)


def fold(old: str | None, number: int, step: dict, here: str, moves: dict[str, str]) -> str:
    """The new step file's body, in its folder `here`: `# Step NN: ...`, Task, Approach, Done when, Notes (the folded
    sections as `###`), Result; the old file's links re-pointed from `steps/`, the row's from the plan folder."""
    body = envelope.split(old)[1] if old and old.startswith("---\n") else (old or "")
    head, parts = text.sections(text.rewrite_links(SIZE_LINE.sub("", body), "steps", here, moves))
    row = lambda value: text.rewrite_links(value, "", here, moves)  # noqa: E731
    keep: dict[str, list[str]] = {k: [] for k in KNOWN}
    folded = []
    for title, part in parts:
        if title in KNOWN:
            keep[title].append(text.strip_blank(part))
        else:
            folded.append(f"### {title}\n\n{text.strip_blank(part)}")
    lead = "\n".join(l for l in COMMENT.sub("", head).splitlines() if not l.startswith("# ")).strip()
    task = "\n\n".join(p for p in [lead, *keep["Task"]] if p) or row(step["title"])
    if len(text.one_line(step["done_when"])) > 200 and not keep["Done when"]:
        keep["Done when"] = [row(step["done_when"])]
    out = [("Task", task), ("Approach", "\n\n".join(keep["Approach"])),
           ("Done when", "\n\n".join(keep["Done when"])), ("Notes", "\n\n".join(keep["Notes"] + folded)),
           ("Result", "\n\n".join(keep["Result"]))]
    return (f"\n# Step {number:02d}: {heading_rest(head, step['title'])}\n"
            + text.join_sections([(k, v) for k, v in out if v.strip()]))


def short(title: str, path: str) -> str:
    """A title whose overview cell `[<title>](<path>)` stays within the 200 characters of a cell (spec:budgets)."""
    return text.cut(title, 200 - len(f"[]({path})"))


def doc_of(plan: int, step: dict, body: str, path: str) -> PlanStep:
    return PlanStep(title=short(step["title"], path),
                    description=text.cut(step["done_when"] or step["title"]), status=step["status"], plan=plan,
                    subplan=1, wave=step["wave"], touches=step["touches"], model=step["model"],
                    effort=step["effort"], window=step["window"], size=step["size"], why=step["why"],
                    was=None if step["id"] == str(step["number"]) else step["id"], body=body)


def convert(folder: Path, plan: int, title: str, goal: str, plan_text: str, run: list[str]) -> dict:
    """Write sub-plan 01 and its steps; move the old step files. Returns {subplan, moves, steps, notes}: `moves`
    old -> new path, `steps` row id -> new path (both relative to the plan folder)."""
    steps, par, notes = read_rows(plan_text, run)
    if not steps:
        return {"subplan": None, "moves": {}, "steps": {}, "notes": notes}
    sid = f"01-{subplan_slug(folder.name)}"
    wide = len(steps) > 99
    new = {s["id"]: f"{shape.SUBPLANS}/{sid}/steps/{sn.step_file(s['number'], wide)}" for s in steps}
    moves = {f"steps/{i}.md": p for i, p in new.items() if (folder / "steps" / f"{i}.md").is_file()}
    sub = Subplan(title=short(title, f"{shape.SUBPLANS}/{sid}/subplan.md"), description=text.cut(plan_folder.describe(goal, title)),
                  status="open", plan=plan, wave=1, schedule="waves" if par else None,
                  body=f"\n# Sub-plan 01: {text.one_line(title)}\n\n## Goal\n\n{goal.strip() or title}\n\n"
                       "## Done when\n\nEvery step done.\n")
    (folder / shape.SUBPLANS / sid / "steps").mkdir(parents=True, exist_ok=True)
    (folder / shape.SUBPLANS / sid / "subplan.md").write_text(sub.render())
    for step in steps:
        old_rel = f"steps/{step['id']}.md"
        old = (folder / old_rel).read_text() if old_rel in moves else None
        target = new[step["id"]]
        body = fold(old, step["number"], step, str(Path(target).parent), moves)
        (folder / target).write_text(doc_of(plan, step, body, target).render())
        if old is not None:
            (folder / old_rel).unlink()
    left = sorted(p.name for p in (folder / "steps").glob("*")) if (folder / "steps").is_dir() else []
    if (folder / "steps").is_dir() and not left:
        (folder / "steps").rmdir()
    notes += [f"steps/{name} matches no row: left in place" for name in left]
    return {"subplan": sid, "moves": moves, "steps": new, "notes": notes}
