"""The foreman's and the servant's page (hal2 plan 0366, step 3): their plan's progress, pure code, plan fields only.

`view(data, ctx)` shows the plan of the field's `CURRENT_PLAN` pointer: title, description, done of total with a bar, the
landing and the field's place in the merge queue, the step table (the next step marked), the next step with its
done-when and the open questions, and, for a farm with a plan store, its home and state ref (plan 0409 step 6: sync on
or off and why, a locked gpg agent, conflicts). The plan is read through `hal2-cli-plans --json` (`plan_cli`: either
home, the plans folder or the store); only without the CLI the files are read. A servant (its `plans/LEAD` names a
foreman's field) shows its foreman's plan from that field's checkout, with the line "servant of <field>". A field
without a plan gets an empty state.
"""

import re
import sys
from pathlib import Path

import plan_cli
import state_sources as src
from skillpath import sibling  # on sys.path since state_sources (plan 0360 D20)

COLUMNS = ["#", "Step", "Done when", "Status"]
QUESTION = re.compile(r"^## (Q\d+)\b[^\n]*·\s*open\s*$(.*?)(?=^## |\Z)", re.M | re.S)
Q_LINE = re.compile(r"^\*\*Q:\*\*\s*(.+)$", re.M)
FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
MAX_TITLE = 140


def plan_module():
    """The plan skill's `plan` module (appended to sys.path like state_sources.steps), None when it is missing."""
    try:
        scripts = sibling("plan", __file__) / "scripts"
        if str(scripts) not in sys.path:
            sys.path.append(str(scripts))
        import plan
        return plan
    except Exception:  # noqa: BLE001  (a missing plan skill never fails the page)
        return None


def front_value(text: str, key: str) -> str:
    """A value of plan.md's front matter, quotes dropped; empty when absent."""
    m = FRONT.match(text)
    for line in (m.group(1).splitlines() if m else []):
        k, _, v = line.partition(":")
        if k.strip() == key:
            return v.strip().strip("\"'")
    return ""


def table_steps(text: str) -> list[dict]:
    """The step table of a plan.md read by hand (the fallback): number, step, done_when, status of each row."""
    steps, cols = [], None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            if steps and cols:
                break
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cols is None:
            if cells[:2] == ["#", "Step"] and "Status" in cells:
                cols = {c.lower().replace(" ", "_"): i for i, c in enumerate(cells)}
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        get = lambda k: cells[cols[k]] if k in cols and cols[k] < len(cells) else ""  # noqa: E731
        steps.append({"number": get("#"), "step": get("step"), "done_when": get("done_when"), "status": get("status")})
    return steps


def is_done(step: dict) -> bool:
    return str(step.get("status") or "").lower().startswith("done")


def read_plan(root: Path, slug: str) -> dict | None:
    """The plan `slug` of the checkout `root`: title, description, landing, land, steps, done, total, next; from
    `hal2-cli-plans` (either home), else from its plan.md; None when neither has it."""
    told = plan_cli.plan(root, slug)
    if told is not None:
        return told
    path = Path(root) / "plans" / slug / "plan.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    mod = plan_module()
    d = {}
    if mod is not None:
        try:
            d = mod.describe_safe(Path(root), path)
        except Exception:  # noqa: BLE001
            d = {}
    steps = d.get("steps") or table_steps(text)
    open_steps = [s for s in steps if not is_done(s)]
    before = [s for s in open_steps if not s.get("after_landing")]
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), slug)
    return {"slug": slug, "title": d.get("title") or title, "description": front_value(text, "description"),
            "landing": d.get("landing") or front_value(text, "landing"), "land": d.get("land") or "",
            "steps": steps, "done": len(steps) - len(open_steps), "total": len(steps),
            "next": (before or open_steps or [None])[0]}


def open_questions(root: Path, slug: str) -> list[str]:
    """`Q31: <the question's first line>` for each open entry of the plan's questions (the CLI's, else questions.md)."""
    told = plan_cli.open_questions(root, slug)
    if told is not None:
        return told
    try:
        text = (Path(root) / "plans" / slug / "questions.md").read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for qid, body in QUESTION.findall(text):
        m = Q_LINE.search(body)
        line = m.group(1).strip() if m else ""
        out.append(f"{qid}: {line[:MAX_TITLE]}{'…' if len(line) > MAX_TITLE else ''}" if line else qid)
    return out


def slug_of(root: str, current: str) -> str | None:
    """The plan a CURRENT_PLAN text names: `<NNNN>-<slug>` also when its folder is not on the disk (a store home)."""
    found = src.plan_of(root, current)["plan_slug"]
    name = current.strip().removesuffix("/plan.md").rstrip("/").removeprefix("plans/")
    return found or (name if src.PLAN_NAME.match(name) and "/" not in name else None)


def lead(root: str) -> tuple[str, str, str] | None:
    """(foreman field, plan, step) of the checkout's `plans/LEAD`, None without a usable marker."""
    parts = src.pointers.read(root, "LEAD").split()
    return (parts[0], parts[1], parts[2]) if len(parts) >= 3 else None


def owner_of(own: dict, rows: list[dict]) -> tuple[dict, str, str]:
    """The row whose plan is shown, its plan text and the servant line: the foreman's for a servant, else the own."""
    marker = lead(own["path"])
    by_wt = {r["wt"]: r for r in rows}
    if marker and marker[0] in by_wt and marker[0] != own["wt"]:
        boss = by_wt[marker[0]]
        plan = marker[1] if src.PLAN_NAME.match(marker[1]) else boss.get("plan") or ""
        return boss, plan, f"servant of {marker[0]}, working step {marker[2]}"
    return own, own.get("plan") or "", ""


def queue_line(row: dict, mode: dict | None) -> str:
    q = row.get("queue")
    text = "not in the merge queue"
    if q:
        text = "holds the toll gate" if q.get("holds") else f"waits in the merge queue, position {q.get('position')}"
    if mode and mode.get("mode") == "smuggle":
        text += " (smuggle mode)"
    return f"Queue: field {row['wt']} {text}"


def empty_view(title: str, own: dict | None, current: str) -> tuple[str, list[dict]]:
    if own is None:
        return title, [{"heading": "Plan", "empty": "This checkout is not one of the repository's worktrees."}]
    note = f" Its CURRENT_PLAN pointer says: {current}" if current else ""
    return title, [{"heading": "Plan", "empty": f"No plan in this field.{note}"}]


def plan_sections(p: dict, row: dict, servant: str, mode: dict | None, questions: list[str],
                  store: list[str] | None = None) -> list[dict]:
    nxt, steps = p["next"], p["steps"]
    items = [i for i in (p["description"], servant, f"Landing: {p['landing']}" + (f" ({p['land']})" if p["land"] else "")
                         if p["landing"] else "", queue_line(row, mode)) if i]
    marked = [i for i, s in enumerate(steps) if nxt is not None and s is nxt]
    return [
        {"heading": p["title"], "items": items},
        {"heading": "Progress", "bar": [p["done"], p["total"]], "text": f"{p['done']} of {p['total']} steps done"},
        {"heading": "Steps", "columns": COLUMNS, "marked": marked, "empty": "The plan has no step table.",
         "rows": [[s.get("number", ""), s.get("step", ""), s.get("done_when", ""), s.get("status", "")] for s in steps]},
        {"heading": "Next step", "empty": "Every step is done.",
         **({"text": f"{nxt.get('number')}: {nxt.get('step')} Done when: {nxt.get('done_when')}"} if nxt else {})},
        {"heading": "Open questions", "items": questions, "empty": "No open questions."},
    ] + ([{"heading": "Plan store", "items": store}] if store else [])


def view(data: dict, ctx: dict) -> tuple[str, list[dict]]:
    import views  # late: views registers this module
    title = views.title_of(ctx)
    rows = data.get("rows") or []
    own = next((r for r in rows if r["wt"] == ctx.get("checkout")), None)
    if own is None:
        return empty_view(title, None, "")
    if not own.get("path"):  # a row without its checkout cannot name a plan
        return empty_view(title, own, own.get("plan") or "")
    boss, current, servant = owner_of(own, rows)
    slug = slug_of(boss["path"], current) if current else None
    p = read_plan(Path(boss["path"]), slug) if slug else None
    if p is None:
        return empty_view(title, own, current)
    questions = open_questions(Path(boss["path"]), slug)
    return title, plan_sections(p, boss, servant, data.get("mode"), questions, plan_cli.store(boss["path"]))
