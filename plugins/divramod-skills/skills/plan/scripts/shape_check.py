"""`plan.py check` on the one plan shape (hal2 plan 0376, design §3, §2 and hal2-records' shape rules,
`code/rust/libs/hal2-records/src/shape_rules*`): the problems of a plan folder with `subplans/`, under the rule ids
hal2-records reports.

- `plan-shape`: the folder parses (shape.load).
- `plan-steps-sized`: every unfinished work step's model, effort, window and size, Size at most 35% of Window, and
  the plan's `run`, from the step files (no step-count limit).
- `spec:budgets`: plan.md's body at most 150 lines outside the generated block, no table cell over 200 characters.
- `overview-current`: the generated block is what the overview renders; `status-derived`: plan.md's and each
  subplan.md's status are the derived ones, `finished` set exactly while the plan is `uat` or `done`.
- `waves-disjoint`: where a level runs by waves, no two items of one wave share a resource that is no machine's.

A sub-plan servant's field (shape_lead) drops its own plan's overview-current and status-derived problems: the
servant never writes plan.md or subplan.md. hal2-cli-records older than 0.7.0 checks plan.md by schema 1 and
reports `schema: 2` itself as a problem: `records_skip` says when its findings on these plans are dropped.
"""
from __future__ import annotations

import functools
import os
import re
import subprocess
from pathlib import Path

import checker
import envelope
import shape
import shape_names as names
import shape_overview as overview
import sizing
from shape_names import ShapeError

LINES = 150
CELL = 200
MIN_RECORDS = (0, 7, 0)  # = .hal/records.toml checker; raise both to 0.7.0 once the landing gives hal2-records that version
DERIVED_RULES = ("overview-current", "status-derived")


def body_lines(text: str) -> int:
    """plan.md's body lines outside the generated overview (its markers and rows not counted)."""
    _, body = envelope.split(text)
    out, inside = 0, False
    for line in body.splitlines():
        if line.strip() == overview.BEGIN:
            inside = True
        elif line.strip() == overview.END:
            inside = False
        elif not inside:
            out += 1
    return out


def budgets(rel: str, text: str) -> list[str]:
    out = []
    if (count := body_lines(text)) > LINES:
        out.append(f"{rel}: the body has {count} lines outside the generated overview, over {LINES} (spec:budgets)")
    _, body = envelope.split(text)
    cells = [c.strip() for line in envelope.prose(body) if line.lstrip().startswith("|")
             for c in re.split(r"(?<!\\)\|", line)]
    if long := next((c for c in cells if len(c) > CELL), None):
        out.append(f"{rel}: a table cell has over {CELL} characters: `{long[:40]}…` (spec:budgets)")
    return out


def sized(rel_of, folder: Path, found: shape.Shape) -> list[str]:
    out = []
    for sub in found.work():
        for step in sub.steps:
            doc = step.doc
            if names.finished(doc.status):
                continue
            at = names.StepRef(sub.id.number, step.number)
            for key in sizing.SIZED:
                if why := sizing.cell_problem(key, getattr(doc, key) or "", doc.window or ""):
                    out.append(f"{rel_of(step.file)}: step {at}: {why} ({sizing.RULE})")
    if out or any(not names.finished(s.doc.status) for sub in found.work() for s in sub.steps):
        run = str(envelope.get((folder / "plan.md").read_text(), "run") or "")
        if why := sizing.run_problem(run):
            out.insert(0, f"{rel_of('plan.md')}: {why} ({sizing.RULE})")
    return out


def derived(rel_of, text: str, found: shape.Shape) -> list[str]:
    out = []
    try:
        current = overview.written("plan.md", text) == overview.render(found)
    except ShapeError as error:
        return [f"{rel_of('plan.md')}: {error} (overview-current)"]
    if not current:
        out.append(f"{rel_of('plan.md')}: the overview is not current: `plan.py overview --write` writes it "
                   "(overview-current)")
    written = overview.written_status(text)
    status = found.derived(written)
    if written != status:
        out.append(f"{rel_of('plan.md')}: status `{written}`, but its steps derive `{status}` (status-derived)")
    if status != "abandoned" and (status in ("uat", "done")) == (not envelope.get(text, "finished")):
        out.append(f"{rel_of('plan.md')}: `finished` is set exactly when the status is `uat` or `done` "
                   "(status-derived)")
    out += [f"{rel_of(sub.file)}: status `{sub.doc.status}`, but its steps derive `{sub.derived()}` (status-derived)"
            for sub in found.subplans if sub.doc.status != sub.derived()]
    return out


def shared(label: str, items: list[tuple[str, int | None, list[str]]]) -> list[str]:
    out = []
    for at, (name, wave, touches) in enumerate(items):
        for other, other_wave, other_touches in items[:at]:
            both = next((t for t in touches if not t.startswith("@") and t in other_touches), None)
            if wave is not None and wave == other_wave and both:
                out.append(f"{label}: {other} and {name} share `{both}` in wave {wave} (waves-disjoint)")
    return out


def disjoint(rel_of, text: str, found: shape.Shape) -> list[str]:
    out = []
    if envelope.get(text, "schedule") == "waves":
        out += shared(rel_of("plan.md"), [(f"sub-plan {s.id}", s.doc.wave, s.doc.touches) for s in found.work()])
    for sub in found.work():
        if sub.doc.schedule == "waves":
            out += shared(rel_of(sub.file), [(f"step {s.number:02d}", s.doc.wave, s.doc.touches) for s in sub.steps])
    return out


def problems(root: Path, folder: Path, lead: bool = False) -> list[str]:
    """Every problem of the schema 2 plan `folder`; `lead`: this field's servant runs one of its sub-plans."""
    base = os.path.relpath(folder.resolve(), root.resolve())
    rel_of = lambda path: f"{base}/{path}"  # noqa: E731
    text = (folder / "plan.md").read_text()
    try:
        found = shape.load(folder)
    except ShapeError as error:
        return [f"{base}: {error} (plan-shape)"]
    out = sized(rel_of, folder, found) + budgets(rel_of("plan.md"), text) + disjoint(rel_of, text, found)
    if not lead:
        out += derived(rel_of, text, found)
    return out


@functools.lru_cache(maxsize=None)
def records_version(cli: str) -> tuple[int, ...] | None:
    try:
        out = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", out.stdout)
    return tuple(int(n) for n in found.groups()) if out.returncode == 0 and found else None


def records_skip(folders: list[Path]) -> str | None:
    """Why hal2-cli-records' findings on the schema 2 plans `folders` are dropped (it is older than 0.7.0, or its
    version is unknown); None when it checks them (or there is none of either)."""
    cli = checker.binary()
    if not folders or cli is None:
        return None
    version = records_version(str(Path(cli).expanduser()))
    if version is not None and version >= MIN_RECORDS:
        return None
    have = ".".join(map(str, version)) if version else "of an unknown version"
    need = ".".join(map(str, MIN_RECORDS))
    return (f"hal2-cli-records {have} is older than {need}: its schema 1 spec is not run on the schema 2 plans "
            f"{', '.join(f.name for f in folders)}")
