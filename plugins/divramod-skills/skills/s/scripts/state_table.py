"""The state table (hal2 plan 0268, D4): the raw rows of `state.collect` as the five cells
`WT | Plan | Steps | State | Waits for` and the line under the table. Pure: no IO. Cells are fixed phrases in a fixed
order joined by `; `; an unknown fact is left out, an empty cell stays empty, a `|` in a cell is escaped.
"""

HEADER = ["WT", "Plan", "Steps", "State", "Waits for"]
QUEUED = {"queued", "waiting", "pending", "requested"}


def age(seconds: int | None) -> str:
    """`5m`, `3h`, `2d` (rounded down); empty when unknown."""
    if seconds is None:
        return ""
    return f"{seconds // 60}m" if seconds < 3600 else f"{seconds // 3600}h" if seconds < 86400 else f"{seconds // 86400}d"


def esc(text: object) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def plan_cell(row: dict) -> str:
    if row["plan_number"] and row["plan_name"]:
        return f"{row['plan_number']} {row['plan_name'].replace('-', ' ')}"
    return row["plan"] or "free"


def steps_cell(row: dict) -> str:
    done, total = row["steps_done"], row["steps_total"]
    return f"{done} of {total}" if done is not None and total is not None else ""


def run_phrase(run: dict) -> str:
    """`check run queued`, `check run running`, `land run running`: a land run is a `land/` branch or a landing workflow."""
    branch, workflow = run.get("branch") or "", (run.get("workflow") or "").lower()
    kind = "land" if branch.startswith("land/") or "land" in workflow or "merge-to-main" in workflow else "check"
    return f"{kind} run {'queued' if run.get('status') in QUEUED else 'running'}"


def state_cell(row: dict, default: str) -> str:
    out = {"busy": ["busy"], "idle": ["idle"], "none": ["no session"]}.get(row["agent"], [])
    q = row["queue"]
    if q:
        out.append("holds the merge queue" if q["holds"] else f"waits in the queue at {q['position']}")
    out += sorted({run_phrase(r) for r in row["ci"]}, key=lambda p: (p.split()[0], p))
    if row["uncommitted"]:
        out.append(f"{row['uncommitted']} uncommitted")
    if row["ahead"]:
        out.append(f"{row['ahead']} {'not pushed' if row['is_main'] else 'not on ' + default}")
    if row["last_commit_age"] is not None:
        out.append(f"last commit {age(row['last_commit_age'])}")
    return "; ".join(out)


def ranges(ids: list[str]) -> list[str]:
    """`Q5`..`Q15` in a row as `Q5-Q15`; two in a row stay apart (`Q19`, `Q20`); other ids as they are."""
    out, i = [], 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j][:1] == "Q" == ids[j + 1][:1] and ids[j][1:].isdigit() \
                and ids[j + 1][1:] == str(int(ids[j][1:]) + 1) and ids[j + 1][1:].isdigit():
            j += 1
        out += [ids[i]] if j - i < 2 else [f"{ids[i]}-{ids[j]}"]
        out += ids[i + 1:j + 1] if j - i == 1 else []
        i = j + 1
    return out


def waits_cell(row: dict) -> str:
    out = []
    for w in row["waits"]:
        kind = w["kind"]
        if kind == "queue":
            if not w.get("holds"):  # the holder is not waiting for the queue, a waiter is
                out.append("the queue")
        elif kind == "ci":
            out.append("the run")
        elif kind == "ask":
            out.append("the farmer's answer")
        elif kind == "unacked":
            out += [f"ack {i}" for i in w["ids"]]
        elif kind == "questions":
            out += ranges(w["open"])
    return "; ".join(out)


def wt_cell(row: dict, nested: bool) -> str:
    """The worktree's name: bold for the checkout the script runs in, `↳ ` before a servant under its foreman's row."""
    return ("↳ " if nested else "") + (f"**{row['wt']}**" if row.get("own") else row["wt"])


def cells(row: dict, default: str, nested: bool = False) -> list[str]:
    """The five cells of a row, as the table prints them (not yet escaped)."""
    return [wt_cell(row, nested), plan_cell(row), steps_cell(row), state_cell(row, default), waits_cell(row)]


def queue_text(queue: list[dict] | None) -> str:
    if queue is None:
        return ""
    if not queue:
        return "empty"
    holder = [t["slot"] for t in queue if t["holding"]]
    waiters = [t["slot"] for t in sorted((t for t in queue if not t["holding"]), key=lambda t: t["position"] or 0)]
    parts = [f"{', '.join(map(str, holder))} holds"] if holder else []
    return "; ".join(parts + ([f"waiting: {', '.join(map(str, waiters))}"] if waiters else []))


def runs_text(runs: list[dict] | None, rows: list[dict]) -> str:
    if runs is None:
        return ""
    if not runs:
        return "none"
    slots = [r["wt"] for r in rows if r["ci"]]
    return f"{len(runs)}" + (f" ({', '.join(slots)})" if slots else "")


def head_text(data: dict) -> str:
    if not data.get("head"):
        return ""
    subject = data.get("head_subject") or ""
    subject = subject if len(subject) <= 60 else subject[:59] + "…"
    return " ".join(x for x in (data["head"], age(data.get("head_age")) + " ago" if data.get("head_age") is not None else "", subject) if x)


def line(data: dict) -> str:
    """`<default>: <sha> <age> ago <subject>; queue: <holder and waiters | empty>; open CI runs: <n (worktrees) | none>`."""
    parts = [f"{data['default']}: {head_text(data)}".rstrip(": ")]
    for label, text in (("queue", queue_text(data["queue"])), ("open CI runs", runs_text(data["runs"], data["rows"]))):
        if text:
            parts.append(f"{label}: {text}")
    return "; ".join(parts)


def table(data: dict) -> str:
    rows = [r.get("cells") or cells(r, data["default"]) for r in data["rows"]]
    head = ["| " + " | ".join(HEADER) + " |", "|" + "---|" * len(HEADER)]
    return "\n".join(head + ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]) + "\n\n" + esc(line(data))
