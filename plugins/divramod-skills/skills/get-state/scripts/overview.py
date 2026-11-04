"""The farm's overview table (hal2 plan 0591, D1): the steward, tollman and farmer on top, then one row per field with a
Claude session, by script, no model. A pure function of `overview_sources.facts`, so the fixture tests pin it.

    overview.py [--repo <path>] [--json]

Columns (D5, plan 0543 D102): wt, plan, name, steps, new (`<done Δ>/<total Δ>` since the previous run), open q, decision?, status, servants (fields whose plans/LEAD names this one),
hands (the session's subagent background tasks), effort (the agent's, else its `--effort` argument), queue (place,
`hitched`, `holds`). A fact that cannot be read is `-` (D3). `--json` prints `{schema: 1, repo, columns, rows}`.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import page

COLUMNS = [("wt", "wt"), ("plan", "plan"), ("name", "name"), ("steps", "steps"), ("new", "new"), ("open_q", "open q"),
           ("decision", "decision?"), ("status", "status"), ("servants", "servants"), ("hands", "hands"),
           ("effort", "effort"), ("queue", "queue")]
SCHEMA = 1
LAST_SCHEMA = 1
NAME_WIDTH = 28
ROLES = ("steward", "tollman", "farmer")


def effort(agent: dict | None, argv_effort: dict) -> str:
    if not agent:
        return "-"
    return agent.get("effort") or argv_effort.get(str(agent.get("pid"))) or "-"


def queue_cell(ticket: dict | None) -> str:
    if not ticket or not isinstance(ticket.get("position"), int):
        return "-"
    return f"{ticket['position'] + 1}" + (" hitched" if ticket.get("ready") else "") + \
        (" holds" if ticket.get("holding") else "")


def tickets(queue: list[dict] | None) -> dict[str, dict]:
    out = {}
    for t in queue or []:
        wt = t.get("slot") or (os.path.basename(t["worktree"]) if t.get("worktree") else None)
        if wt:
            out[wt] = t
    return out


def role_agent(facts: dict, role: str) -> dict | None:
    """The live session of the steward (the main checkout), the tollman or the farmer (`<role>-<repo>`)."""
    if role == "steward":
        return facts["agents"].get(facts["main"])
    name = f"{role}-{facts['repo']}"
    return next((facts["agents"].get(f["path"]) for f in facts["fields"] if f["wt"] == name), None)


def role_row(facts: dict, role: str) -> dict:
    a = role_agent(facts, role)
    status = "-" if a is None and not facts.get("agents_known", True) else \
        (f"online ({a.get('state') or '-'})" if a else "offline")
    if role == "tollman":
        status += f", timer {facts.get('timer') or '-'}"
    return {**{k: "-" for k, _ in COLUMNS}, "wt": role, "status": status,
            "effort": effort(a, facts.get("argv_effort") or {})}


def delta(n: int | None) -> str:
    """A change as the column shows it: `+2`, `-1`, `-` for none."""
    return "-" if not n else f"{n:+d}"


def key_of(wt: str, pp: dict) -> str:
    return f"{wt}:{pp.get('number')}"


def new_cell(wt: str, pp: dict, last: dict, servant: bool) -> str:
    """`+2/+5`, `-/-`, `+1/-3`: done and total against the previous run; `-/-` for a servant's or with no earlier run at all;
    a field new since the earlier run counts all its steps as new (`+done/+total`, D105)."""
    done, total = pp.get("done"), pp.get("total")
    key = key_of(wt, pp)
    prev_d, prev_t = (last.get("done") or {}).get(key), (last.get("total") or {}).get(key)
    if servant or not (last.get("done") or last.get("total")):
        return "-/-"
    dd = done - (prev_d or 0) if done is not None else 0
    dt = total - (prev_t or 0) if total is not None else 0
    return f"{delta(dd)}/{delta(dt)}"


def snapshot(facts: dict) -> dict:
    """What the next run compares with: done and total per `field:plan` of every non-servant field with steps."""
    out: dict = {"schema": LAST_SCHEMA, "done": {}, "total": {}}
    for f in facts["fields"]:
        pp = ((facts["agents"].get(f["path"]) or {}).get("plan_progress")) or {}
        if pp.get("done") is not None and pp.get("total") is not None and not f.get("lead"):
            out["done"][key_of(f["wt"], pp)], out["total"][key_of(f["wt"], pp)] = pp["done"], pp["total"]
    return out


def last_path(repo: str) -> Path:
    """`<state dir>/overview-last-<repo>.json` (the skill's state dir, never in a checkout; retention `keep`: one
    small file per repo, overwritten by every table run)."""
    return page.state_dir() / f"overview-last-{re.sub(r'[^A-Za-z0-9._]+', '-', repo).strip('-') or 'x'}.json"


def load_last(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and d.get("schema") == LAST_SCHEMA else {}
    except (OSError, ValueError):
        return {}


def save_last(path: Path, snap: dict) -> None:
    """Atomic: a temp file beside it, then `os.replace`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(snap), encoding="utf-8")
    os.replace(tmp, path)


def field_row(facts: dict, field: dict, agent: dict, servants: dict, queue: dict, last: dict | None = None) -> dict:
    wt, pp = field["wt"], agent.get("plan_progress") or {}
    q = (facts.get("questions") or {}).get(wt) or []
    done, total = pp.get("done"), pp.get("total")
    hands = sum(1 for t in agent.get("background_tasks") or [] if isinstance(t, dict) and t.get("type") == "subagent")
    number = pp.get("number")
    return {"wt": wt, "plan": f"{number:04d}" if isinstance(number, int) else "-",
            "name": (pp.get("title") or "-")[:NAME_WIDTH], "steps": f"{done}/{total}" if total else "-",
            "new": new_cell(wt, pp, last or {}, bool(field.get("lead"))) if total else "-",
            "open_q": str(len(q)) if pp.get("slug") else "-",
            "decision": "yes" if q or wt in (facts.get("asks") or []) else "-",
            "status": (agent.get("state") or "-") + (" (plan done)" if total and done == total else ""),
            "servants": str(servants.get(wt, 0)), "hands": str(hands),
            "effort": effort(agent, facts.get("argv_effort") or {}), "queue": queue_cell(queue.get(wt))}


def rows(facts: dict, last: dict | None = None) -> list[dict]:
    """The role rows, then one row per field with a live Claude session (not the farmer's or tollman's), by name."""
    servants: dict[str, int] = {}
    for f in facts["fields"]:
        if f.get("lead"):
            servants[f["lead"]] = servants.get(f["lead"], 0) + 1
    queue = tickets(facts.get("queue"))
    out = [role_row(facts, r) for r in ROLES]
    for f in sorted(facts["fields"], key=lambda f: f["wt"]):
        agent = facts["agents"].get(f["path"])
        if agent and not f["wt"].startswith(("farmer-", "tollman-")):
            out.append(field_row(facts, f, agent, servants, queue, last))
    return out


def render(table: list[dict]) -> list[str]:
    """The aligned Markdown table's lines: header, rule, one line per row."""
    head = [h for _, h in COLUMNS]
    cells = [[r[k] for k, _ in COLUMNS] for r in table]
    w = [max(len(c[i]) for c in cells + [head]) for i in range(len(head))]
    line = lambda c: "| " + " | ".join(x.ljust(w[i]) for i, x in enumerate(c)) + " |"  # noqa: E731
    return [line(head), "|" + "|".join("-" * (x + 2) for x in w) + "|", *(line(c) for c in cells)]


def payload(facts: dict, last: dict | None = None) -> dict:
    return {"schema": SCHEMA, "repo": facts["repo"], "columns": [k for k, _ in COLUMNS], "rows": rows(facts, last)}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="The farm's overview table.")
    p.add_argument("--repo", default=os.getcwd(), help="a path inside the repository (default: the current folder)")
    p.add_argument("--json", action="store_true", help="the rows as JSON (schema 1)")
    args = p.parse_args(argv)
    import overview_sources
    facts = overview_sources.facts(args.repo)
    path = last_path(facts["repo"])
    last = load_last(path)
    print(json.dumps(payload(facts, last), indent=2) if args.json else "\n".join(render(rows(facts, last))))
    if facts.get("agents_known", True):
        save_last(path, snapshot(facts))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
