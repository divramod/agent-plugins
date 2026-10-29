"""masterplan.py: a masterplan in the plan skill (hal2 plan 0275 step 4; its decisions D1, D2, D13, D26, D30, D34).

A masterplan is a Plan record whose rows are plans, each with its own folder, foreman and bring in. It is known by
its slug's marker (`<NNNN>-masterplan[-<slug>]`) and by naming no `parent`; a plan names its masterplan by the front
matter key `parent`, and a plan with a `parent` is never a masterplan, whatever its slug says. This module is the
skill's one place for the word; plan.py only wires it in.

- the kind: `has_marker`, `is_masterplan`, `of`; a new masterplan's slug (`marked`) and its crop (`pick_crop`: the
  first of `CROPS` that no unfinished masterplan in any checkout of the repository uses);
- `new --parent <n>`: `adopt` writes the plan's `parent`, its Context line and the masterplan's `draft` row;
- a masterplan's rows are no steps: `refuse_step` (prompt, uat); `fields`: what every command's JSON says;
- a servant's field (`plans/LEAD`): `servant_refusal`, the words of plan.py's refusal there.

`plan.py masterplan` prints through masterplan_view.py. A plan file is read as UTF-8 whatever the locale says (`read`);
a masterplan's plan.md is written with its line ends as they are, through a temp file (`raw`, `write`).
"""
import os
import re
import shutil
from pathlib import Path

import envelope
import parallel
import plan_number
import planhome
import table

MARKER = "masterplan"
# The twelve crops in the order a new masterplan picks from: the `values` of the Plan key `crop` in hal2-records'
# specs/plan.toml and hal2-plans' table (a test holds the three equal where the spec is there).
CROPS = ("wheat", "corn", "sunflower", "potato", "carrot", "pumpkin", "apple", "grape", "hop", "tomato", "cabbage",
         "beet")
MAIN = "plan.md"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "masterplan.md"
SLUG = re.compile(r"^\d{4}-[a-z0-9-]+$")
LINK = re.compile(r"\[[^\]]*\]\(\.\./(\d{4}-[a-z0-9-]+)/plan\.md(?:\s[^)]*)?\)")
DRAFT = "draft"
FINISHED = ("done", "abandoned")
NO_STEPS = ("prompt", "uat")
NO_TABLE = "{slug} has no step table with the columns '#', 'Step' and 'Status' to write the plan's row into"
SLUG_CHARS = 60


class MasterplanError(Exception):
    pass


def has_marker(slug: str) -> bool:
    """The slug says the plan may be a masterplan (`<NNNN>-masterplan[-<slug>]`): where only a slug is at hand the
    plan's front matter decides (`is_masterplan`)."""
    name = slug[5:] if SLUG.match(slug) else ""
    return name == MARKER or name.startswith(MARKER + "-")


def is_masterplan(slug: str, parent: int | None) -> bool:
    """The skill's one function for the kind: the marker in the slug and no `parent`. `0275-masterplan-tools` with
    `parent: 274` is a plan of masterplan 0274."""
    return has_marker(slug) and parent is None


def marked(slug: str) -> str:
    """A new masterplan's slug after its number, `masterplan-<slug>`; a slug that starts with the word is not
    prefixed twice."""
    if slug == MARKER or slug.startswith(MARKER + "-"):
        return slug
    return f"{MARKER}-{slug}"[:SLUG_CHARS].rstrip("-")


def slug_of(path: Path) -> str:
    return path.parent.name if path.name == MAIN else path.stem


def read(path: Path) -> str:
    """A plan file's text to read: UTF-8, every line end as `\\n`."""
    return path.read_text(encoding="utf-8")


def raw(path: Path) -> str:
    """A plan file's text to rewrite: UTF-8 with its line ends as they are (a CRLF file stays one)."""
    return path.read_bytes().decode("utf-8")


def write(path: Path, text: str) -> None:
    """Write `text` (line ends as given) over the plan file at `path` in one move: a temp file beside it, then
    `os.replace`, so no reader of the masterplan sees half a file."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(text.encode("utf-8"))
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def key(text: str, name: str):
    """One front matter key of a plan's text; None for a legacy plan, a missing key or broken front matter."""
    try:
        return envelope.get(text, name)
    except envelope.FormatError:
        return None


def parent_of(text: str) -> int | None:
    value = key(text, "parent")
    return value if isinstance(value, int) else None


def of_text(slug: str, text: str) -> bool:
    return has_marker(slug) and is_masterplan(slug, parent_of(text))


def of(path: Path) -> bool:
    """Is the plan at `path` (its plan.md) a masterplan? Reads the file only when the slug has the marker."""
    return has_marker(slug_of(path)) and of_text(slug_of(path), read(path))


def find(plans: Path, number: int) -> Path | None:
    """The plan.md of the plan numbered `number` in the plans folder `plans`."""
    return next(iter(sorted(plans.glob(f"{number:04d}-*/{MAIN}"))), None)


def rows(text: str) -> list[dict]:
    """A masterplan's step table as rows of plans: each row's number, the slug of the plan its Step cell links
    (the first link `../<slug>/plan.md`; None without one), the cell's other words, its status and its Needs."""
    lines = text.splitlines()
    found = table.header(lines)
    if found is None:
        return []
    at, cols = found
    out = []
    for _, cells in table.rows(lines, at):
        cell = lambda name: cells[cols[name]] if name in cols and cols[name] < len(cells) else ""  # noqa: E731
        step = cell("step")
        link = LINK.search(step)
        label = step[:link.start()] + step[link.end():] if link else step
        out.append({"number": cell("#"), "plan": link.group(1) if link else None, "label": " ".join(label.split()),
                    "status": cell("status"), "needs": parallel.parse_needs(cell("needs"))[0]})
    return out


def row_of(path: Path, parent: int) -> str | None:
    """The number of the row that links the plan at `path` in its masterplan `parent`; None when this checkout has
    no such masterplan or no row links the plan."""
    master = find(path.parent.parent, parent) if path.name == MAIN else None
    if master is None or not of(master):
        return None
    return next((r["number"] for r in rows(read(master)) if r["plan"] == slug_of(path)), None)


def fields(path: Path, text: str) -> dict:
    """What every command's JSON says of a plan: `masterplan` (true for one) with its `crop`, `parent` (the number
    its front matter names) and, for a plan of a masterplan, its `row` there."""
    slug, parent = slug_of(path), parent_of(text)
    one = is_masterplan(slug, parent)
    return {"masterplan": one, "crop": str(key(text, "crop") or "") if one else "", "parent": parent,
            "row": row_of(path, parent) if parent is not None else None}


def master_of(path: Path) -> Path:
    """The masterplan the plan at `path` is or is a plan of."""
    slug, parent = slug_of(path), parent_of(read(path))
    if is_masterplan(slug, parent):
        return path
    master = find(path.parent.parent, parent) if parent is not None and path.name == MAIN else None
    if master is None or not of(master):
        raise MasterplanError(f"{slug} is no masterplan and no plan of one (its `parent` names none in this "
                              "checkout): name the masterplan with --plan <n>")
    return master


def masterplan_files(root: Path) -> list[Path]:
    """Every masterplan's plan.md the farm knows: in the store home the view's (the store is the farm's one copy, so
    `new --masterplan` renders all of it: storerun.py), else the plans folder of every checkout of the repository."""
    pattern = f"[0-9][0-9][0-9][0-9]-{MARKER}*/{MAIN}"
    view = planhome.view_of(root)
    if view is not None:
        return sorted(view.glob(pattern))
    return [path for tree in plan_number.worktree_paths(root) for path in (tree / "plans").glob(pattern)]


def used_crops(root: Path) -> dict[str, set[str]]:
    """crop -> the unfinished masterplans that use it, over the plans folder of every checkout of the repository
    (the store home: the store's, `masterplan_files`).
    A masterplan's copies count once, and it is finished as soon as one copy says so: a checkout that was not
    restocked still holds the open one. A copy that cannot be read (another field's half-written or broken file)
    is skipped: it never stops `new --masterplan`."""
    crops: dict[str, str] = {}
    finished: set[str] = set()
    for path in masterplan_files(root):
        try:
            text, slug = read(path), slug_of(path)
        except (OSError, UnicodeDecodeError):
            continue
        if not of_text(slug, text):
            continue
        if key(text, "status") in FINISHED:
            finished.add(slug)
        elif crop := key(text, "crop"):
            crops[slug] = str(crop)
    used: dict[str, set[str]] = {}
    for slug, crop in crops.items():
        if slug not in finished:
            used.setdefault(crop, set()).add(slug)
    return used


def pick_crop(root: Path) -> str:
    """A new masterplan's crop: the first of `CROPS` no unfinished masterplan uses; when all twelve are in use,
    the one the fewest use, the first of those in the list's order."""
    used = used_crops(root)
    return min(CROPS, key=lambda crop: len(used.get(crop, ())))


def template(root: Path, values: dict) -> str:
    """templates/masterplan.md filled in: plan.py's values of a new plan folder and the picked crop."""
    return read(TEMPLATE).format(**values, crop=pick_crop(root))


def check_new(is_master: bool, research: bool, parent: Path | None) -> Path | None:
    """`plan.py new`'s flags: `--masterplan` goes with neither `--parent` nor `--research`, and `--parent` names a
    masterplan (`parent`: its plan.md) whose row can be written: checked here, before the new plan's folder and
    `CURRENT_PLAN` are, so a refusal leaves nothing behind. The masterplan the new plan is a plan of, or None."""
    if is_master and parent is not None:
        raise MasterplanError("--masterplan and --parent do not go together: a masterplan names no parent, and a "
                              "plan with a `parent` is a plan of that masterplan")
    if is_master and research:
        raise MasterplanError("--masterplan and --research do not go together: a masterplan holds plans, a research "
                              "plan of it is `new --parent <n> --research`")
    if parent is not None and not of(parent):
        raise MasterplanError(f"--parent names {slug_of(parent)}, which is no masterplan: a masterplan's slug is "
                              f"`<NNNN>-{MARKER}-<slug>` and it names no `parent` (`new --masterplan` writes one)")
    if parent is not None and parent.name != MAIN:
        raise MasterplanError(f"--parent names {slug_of(parent)}, a flat plan file: this checkout has no folder "
                              f"plans/{slug_of(parent)}/ for the new plan to link (move it to plans/"
                              f"{slug_of(parent)}/{MAIN})")
    if parent is not None and table.header(read(parent).splitlines()) is None:
        raise MasterplanError(NO_TABLE.format(slug=slug_of(parent)))
    return parent


def add_row(master: Path, slug: str, title: str, ref: str | None) -> str:
    """Append the `draft` row of plan `slug` to the masterplan's table: the link and the title, Who `lead`, the
    done-when "brought in" (`ref`: the default branch's ref). The row's number: the highest one plus one."""
    text = raw(master)
    lines = text.split("\n")
    found = table.header(lines)
    if found is None:
        raise MasterplanError(NO_TABLE.format(slug=slug_of(master)))
    at, cols = found
    old = table.rows(lines, at)
    number = str(max((int(r["number"]) for r in rows(text) if r["number"].isdigit()), default=0) + 1)
    where = f"`{ref}`" if ref else "the default branch"
    values = {"#": number, "step": f"[{slug[:4]}](../{slug}/{MAIN}) {title}", "who": "lead", "status": DRAFT,
              "done when": f"plan {slug[:4]} is brought in: its {MAIN} on {where} says `status: done`"}
    cells = [""] * table.width(lines, at)
    for name, value in values.items():
        if name in cols:
            cells[cols[name]] = value
    lines.insert((old[-1][0] if old else at + 1) + 1, table.join_row(cells) + table.eol(lines[at]))
    write(master, "\n".join(lines))
    return number


def under_context(text: str, line: str) -> str:
    """`text` with `line` as the first line of its `## Context`."""
    lines = text.split("\n")
    for i, found in enumerate(lines):
        if found.strip() == "## Context":
            blank = i + 1 < len(lines) and not lines[i + 1].strip()
            lines.insert(i + 2 if blank else i + 1, line)
            break
    return "\n".join(lines)


def adopt(master: Path, child: Path, ref: str | None = None) -> str:
    """`new --parent`: make the new plan at `child` a plan of the masterplan at `master`: the masterplan's `draft`
    row for it, the plan's `parent` and the masterplan linked first under its Context. The row's number."""
    slug, home = slug_of(child), slug_of(master)
    text = read(child)
    row = add_row(master, slug, str(key(text, "title") or slug[5:]), ref)
    text = envelope.set_key(text, "parent", str(int(home[:4])))
    child.write_text(under_context(text, f"- [Masterplan {home[:4]}](../{home}/{MAIN}), row {row}: this plan is a "
                                         "plan of it, brought in alone."), encoding="utf-8")
    return row


def refuse_step(path: Path, command: str, step: str = "") -> None:
    """`prompt <n>` and `uat` on a masterplan: its rows are plans, no steps. One line that names the row's plan."""
    if command not in NO_STEPS or not of(path):
        return
    number, found = slug_of(path)[:4], rows(read(path))
    if command == "prompt":
        row = next((r for r in found if r["number"] == step), None)
        if row is None:
            raise MasterplanError(f"no row '{step}' in masterplan {number}")
        target = row["plan"] or "<the row's plan>"
        raise MasterplanError(f"plan {number} is a masterplan: its row {step} is a plan, no step, and runs in no "
                              f"subagent; work on that plan: `plan.py use {target}`, then `plan.py prompt <n>` for "
                              f"its steps (a servant, whose field keeps naming the masterplan: `plan.py prompt <n> "
                              f"--plan {target}`)")
    row = next((r for r in found if r["plan"] and not r["status"].lower().startswith("done")), None)
    target = row["plan"] if row else "<a row's plan>"
    raise MasterplanError(f"plan {number} is a masterplan: it has no UATs of its own, each of its plans writes its "
                          f"own; `plan.py use {target}`, then `plan.py uat`")


def servant_refusal(marker: dict, command: str) -> str:
    """Why plan.py refuses `command` in a servant's field (`marker`: its plans/LEAD, `<foreman's field> <plan>
    <step, or the masterplan's row>`), and what the servant does instead."""
    field, plan = marker["slot"], marker["plan"]
    part = "row" if has_marker(plan) else "step"
    return (f"this field is a servant of the foreman in field {field} (plan {plan} {part} {marker['step']}): "
            f"`{command}` is the foreman's, who alone edits plan.md and brings the work in. Do your steps, commit "
            f"them, write each step file's Notes and report to the foreman in field {field}, who marks the step "
            f"there (`plan.py status <step> <status> --plan <plan>`)")
