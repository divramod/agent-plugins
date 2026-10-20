"""The farmer's page (hal2 plans 0366 D1, D6; 0369 D3, D7, D8): three `grid` tables over the fields (numbered
worktrees), pure: reads `state.collect`'s dict only, no IO, no model call.

- `queue`: the merge queue's tickets in queue order (holder first), a Place column first; the mode line is the note.
- `fields`: the fields with a plan, filters Done / One step left / Nearly done / The rest / All (default All; the
  groups of `group_of`), sorted by done percentage, highest first.
- `free`: the fields with no plan at all, by field number.

All three share one column set (`COLUMNS`): Field | Plan | Steps | Done % (hidden) | What it brings in | State | ↓ ↑ s ?
+ ~ - (the statusline's numbers, empty when unknown). `table(data, id)` builds one table, so a server can serve
`/table/<id>`; a new table is one builder in `TABLES` and its id in `TABLE_IDS`.
"""

import ledger_sources
import state_table

DEFAULTS = {"plan": "", "plan_number": None, "plan_name": None, "steps_done": None, "steps_total": None,
            "done_pct": None, "git": None, "agent": None, "queue": None, "waits": [], "own": False, "description": None}
NUMBERS = [("behind", "↓"), ("ahead", "↑"), ("stash", "s"), ("untracked", "?"), ("added", "+"), ("modified", "~"),
           ("deleted", "-")]
COLUMNS = ([{"key": "wt", "label": "Field", "type": "text"}, {"key": "plan", "label": "Plan", "type": "text"},
            {"key": "steps", "label": "Steps", "type": "text"},
            {"key": "done_pct", "label": "Done %", "type": "num", "hidden": True},
            {"key": "brings", "label": "What it brings in", "type": "text"},
            {"key": "state", "label": "State", "type": "text"}]
           + [{"key": k, "label": label, "type": "num"} for k, label in NUMBERS])
GROUP_FILTERS = [("done", "Done"), ("one", "One step left"), ("nearly", "Nearly done"), ("rest", "The rest")]
TABLE_IDS = ["queue", "jobs", "fields", "free", "questions", "decisions"]


def is_field(row: dict) -> bool:
    """A numbered worktree; the main checkout and the role worktrees (`farmer-hal2`, `tollman-hal2`) are no field."""
    return not row.get("is_main") and row["wt"].isdigit()


def group_of(row: dict) -> str:
    done, total = row["steps_done"], row["steps_total"]
    if not row["plan"]:
        return "free"
    if done is None or not total:
        return "rest"
    if done >= total:
        return "done"
    if total - done == 1:
        return "one"
    return "nearly" if done * 3 >= total * 2 else "rest"


def state_cell(row: dict, smuggle: bool) -> str:
    out = {"busy": ["busy"], "idle": ["idle"], "none": ["no session"]}.get(row["agent"], [])
    q = row["queue"]
    if q:
        out.append("holds the merge queue" if q["holds"] else f"queue {q['position']}")
        if q.get("red"):
            out.append(f"red: {state_table.red_phrase(q['red'])}")
        if smuggle:
            out.append("smuggling")
    for w in row["waits"]:
        if w["kind"] == "questions" and w["open"]:
            out.append("waits on " + ", ".join(state_table.ranges(w["open"])))
    return "; ".join(out)


def mode_line(mode: dict | None) -> str:
    """`Merge queue mode: production`, `... smuggle since <at> by <who>` (what is known), `... unknown`."""
    if not mode or not mode.get("mode"):
        return "Merge queue mode: unknown"
    if mode["mode"] != "smuggle":
        return f"Merge queue mode: {mode['mode']}"
    since = mode.get("since") or mode.get("at")
    return "Merge queue mode: smuggle" + (f" since {since}" if since else "") + (f" by {mode['by']}" if mode.get("by") else "")


def cells(row: dict, smuggle: bool) -> dict:
    """One grid row (keys of `COLUMNS`, the hidden `group` the filters match, `_marked` for the own field)."""
    git = row["git"] or {}
    return {"wt": row["wt"], "plan": state_table.plan_cell(row) if row["plan"] else "", "steps": state_table.steps_cell(row),
            "done_pct": row["done_pct"], "brings": row.get("description") or "", "state": state_cell(row, smuggle),
            **{k: git.get(k) for k, _ in NUMBERS}, "group": group_of(row), "_marked": bool(row.get("own"))}


def fields_of(data: dict) -> list[dict]:
    """The numbered fields in number order, each over `DEFAULTS` (a sparse row does not raise)."""
    return sorted(({**DEFAULTS, **r} for r in data["rows"] if is_field(r)), key=lambda r: int(r["wt"]))


def smuggling(data: dict) -> bool:
    return (data.get("mode") or {}).get("mode") == "smuggle"


def queue_table(data: dict) -> dict:
    by_wt = {r["wt"]: {**DEFAULTS, **r} for r in data["rows"]}
    rows = []
    for i, t in enumerate(data.get("queue") or [], 1):
        row = by_wt.get(t.get("wt")) or {**DEFAULTS, "wt": t.get("wt") or "?"}
        row = {**row, "queue": row["queue"] or {"holds": t.get("holding"), "position": t.get("position")}}
        rows.append({"place": i, **cells(row, smuggling(data))})
    empty = "The merge queue is empty." if data.get("queue") is not None else "The merge queue is not known."
    return {"kind": "grid", "id": "queue", "heading": "Merge queue", "note": mode_line(data.get("mode")),
            "columns": [{"key": "place", "label": "Place", "type": "num"}, *COLUMNS], "rows": rows, "empty": empty}


def jobs_table(data: dict) -> dict:
    """The workqueue's running jobs (plan 0382 step 5): field, class, head, running for; a missing CLI shows an empty table."""
    rows = [{"wt": j.get("field") or "?", "class": j.get("class") or "", "head": j.get("head") or "",
             "running": state_table.running_for(j.get("since")), "flags": ", ".join(j.get("flags") or [])}
            for j in data.get("jobs") or []]
    cols = [("wt", "Field"), ("class", "Class"), ("head", "Job"), ("running", "Running for"), ("flags", "Marks")]
    return {"kind": "grid", "id": "jobs", "heading": "Running jobs", "columns": [{"key": k, "label": label, "type": "text"} for k, label in cols],
            "rows": rows, "empty": "No heavy job runs." if data.get("jobs") is not None else "The workqueue is not known."}


def fields_table(data: dict) -> dict:
    rows = [cells(r, smuggling(data)) for r in fields_of(data) if r["plan"]]
    filters = [{"key": k, "label": label, "match": {"group": [k]}} for k, label in GROUP_FILTERS]
    return {"kind": "grid", "id": "fields", "heading": "Fields with a plan", "columns": COLUMNS, "rows": rows,
            "filters": [*filters, {"key": "all", "label": "All", "match": None}], "filter": "all",
            "sort": {"key": "done_pct", "dir": "desc"}, "empty": "No field has a plan."}


def free_table(data: dict) -> dict:
    rows = [cells(r, smuggling(data)) for r in fields_of(data) if not r["plan"]]
    return {"kind": "grid", "id": "free", "heading": "Free fields", "columns": COLUMNS, "rows": rows,
            "sort": {"key": "wt", "dir": "asc"}, "empty": "No free field."}


def ledger(data: dict, key: str, read) -> list[dict]:
    """The ledger rows: `data[key]` when the caller put them there (a test, a server cache), else read from the fields."""
    found = data.get(key)
    return found if found is not None else read(data["rows"])


def questions_table(data: dict) -> dict:
    """Every question of every field's plan; Open by default (D11). Options are one cell, `a) ...; b) ...`."""
    rows = [{"wt": q["wt"], "plan": q["plan"], "n": q["n"], "question": q["question"],
             "options": "; ".join(f"{'abc'[i] if i < 3 else i + 1}) {o}" for i, o in enumerate(q.get("options") or [])),
             "answer": q.get("answer") or "", "state": q.get("state") or ""} for q in ledger(data, "questions", ledger_sources.questions)]
    cols = [("wt", "Field"), ("plan", "Plan"), ("n", "Q"), ("question", "Question"), ("options", "Options"),
            ("answer", "Answer"), ("state", "State")]
    filters = [{"key": "open", "label": "Open", "match": {"state": ["open"]}},
               {"key": "answered", "label": "Answered", "match": {"state": ["answered"]}},
               {"key": "all", "label": "All", "match": None}]
    return {"kind": "grid", "id": "questions", "heading": "Questions", "columns": [{"key": k, "label": label, "type": "text"} for k, label in cols],
            "rows": rows, "filters": filters, "filter": "open", "empty": "No questions."}


def decisions_table(data: dict) -> dict:
    """Every ledger entry of every field's plan; In force by default (D12), newest date first; Words and Why hidden."""
    rows = [{"wt": d["wt"], "plan": d["plan"], "n": d["n"], "date": d["date"], "who": d["who"], "state": d["state"],
             "decision": d["decision"], "words": d["words"], "why": d["why"]} for d in ledger(data, "decisions", ledger_sources.decisions)]
    cols = [("wt", "Field", False), ("plan", "Plan", False), ("n", "D", False), ("date", "Date", False), ("who", "Who", False),
            ("state", "State", False), ("decision", "Decision", False), ("words", "Words", True), ("why", "Why", True)]
    filters = [{"key": "force", "label": "In force", "match": {"state": ["in-force", "promoted"]}},
               {"key": "all", "label": "All", "match": None}]
    return {"kind": "grid", "id": "decisions", "heading": "Decisions",
            "columns": [{"key": k, "label": label, "type": "text", **({"hidden": True} if hidden else {})} for k, label, hidden in cols],
            "rows": rows, "filters": filters, "filter": "force", "sort": {"key": "date", "dir": "desc"}, "empty": "No decisions.",
            "static": False}  # about 1000 rows: drawn by the script only, the page stays small (D14)


TABLES = {"queue": queue_table, "jobs": jobs_table, "fields": fields_table, "free": free_table, "questions": questions_table,
          "decisions": decisions_table}


def table(data: dict, table_id: str) -> dict | None:
    """One table's grid section by id (what `GET /table/<id>` serves), None for an unknown id."""
    build = TABLES.get(table_id)
    return build(data) if build else None


def view(data: dict, ctx: dict) -> tuple[str, list[dict]]:
    import views  # late: views registers this module
    return views.title_of(ctx), [table(data, i) for i in TABLE_IDS]
