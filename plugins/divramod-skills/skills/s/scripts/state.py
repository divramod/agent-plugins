#!/usr/bin/env python3
"""The state call, `/s` (hal2 plan 0268): one row per worktree slot of the repository, collected as code, no model.

    state.py [--repo <path>] [--json]

Prints the table (the own row's WT bold, a foreman's servants under its row as `↳ <WT>`) `WT | Plan | Steps | State | Waits for` and a line under it (state_table.py), or with --json
{repo, default, head, head_age, head_subject, queue, runs, rows}: the raw facts per slot (`wt`, `path`, `branch`, `plan` = the text of
plans/CURRENT_PLAN, `plan_number`, `plan_name`, `steps_done`, `steps_total`, `own` the checkout the script runs in, `foreman` the slot named by plans/LEAD (or null), `agent` busy|idle|none, `agent_state`,
`last_commit_age` seconds, `uncommitted`, `ahead` commits not on origin/<default> (the main checkout: not pushed),
`queue`, `ci` the slot's open runs, `waits` fact dicts, `cells` the five table cells). A fact that cannot be known is None (a missing, failing or
slow tool never raises). Rows: numbered slots by number, named slots by name, the main checkout last as `main`; dot
checkouts and prunable worktrees are no slots. Only reads: no fetch, no write.
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import farmer_link as fl
import state_sources as src
import state_table

POOL = 8


def slot_key(row: dict) -> tuple:
    name = row["wt"]
    if row["is_main"]:
        return (2, 0, name)
    return (0, int(name), name) if name.isdigit() else (1, 0, name)


def arrange(rows: list[dict]) -> set[str]:
    """Moves each servant (a slot whose plans/LEAD names a foreman slot of this table) directly under its foreman's row,
    the servants of one foreman by number, in place; returns the slots that now stand nested."""
    by_wt = {r["wt"]: r for r in rows}
    kids = {}
    for r in rows:
        f = r["foreman"]
        if f and f != r["wt"] and f in by_wt:
            kids.setdefault(f, []).append(r)
    nested = {k["wt"] for ks in kids.values() for k in ks}
    out = []
    for r in rows:
        if r["wt"] not in nested:
            out.append(r)
            out += sorted(kids.get(r["wt"], []), key=slot_key)
    rows[:] = out
    return nested


def default_branch(main: str) -> str:
    return (src.git(main, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") or "").removeprefix("origin/") or "main"


def count(path: str, *args: str) -> int | None:
    out = src.git(path, *args)
    return int(out) if out is not None and out.isdigit() else None


def git_facts(path: str, base: str) -> dict:
    """Last commit's age in seconds, uncommitted entries, commits ahead of `base` (None each when unknown)."""
    stamp = src.git(path, "log", "-1", "--format=%ct")
    status = src.git(path, "status", "--porcelain")
    return {"last_commit_age": max(0, int(time.time()) - int(stamp)) if stamp and stamp.isdigit() else None,
            "uncommitted": len(status.splitlines()) if status is not None else None,
            "ahead": count(path, "rev-list", "--count", f"{base}..HEAD")}


def current_plan(path: str) -> str:
    try:
        return (Path(path) / "plans" / "CURRENT_PLAN").read_text().strip()
    except OSError:
        return ""


def agent_facts(by_path: dict | None, path: str) -> dict:
    if by_path is None:
        return {"agent": None, "agent_state": None}
    a = by_path.get(os.path.realpath(path))
    if a is None:
        return {"agent": "none", "agent_state": None}
    return {"agent": "busy" if a.get("state") in fl.BUSY else "idle", "agent_state": a.get("state")}


def queue_fact(tickets: list[dict] | None, path: str, wt: str) -> dict | None:
    for t in tickets or []:
        if t["worktree"] == os.path.realpath(path) or (t["worktree"] is None and t["slot"] == wt):
            return {"holds": t["holding"], "position": t["position"], "state": t["state"]}
    return None


def waits_of(row: dict, log: list[dict] | None, asking: set, unacked: dict, questions: list[str]) -> list[dict]:
    """The facts a slot waits for, in a fixed order: the queue, a CI run, an open ask, unacked instructions, plan questions."""
    out = []
    if row["queue"]:
        out.append({"kind": "queue", **{k: row["queue"][k] for k in ("holds", "position")}})
    if row["ci"]:
        out.append({"kind": "ci", "runs": row["ci"]})
    if row["wt"] in asking:
        out.append({"kind": "ask"})
    if unacked.get(row["wt"]):
        out.append({"kind": "unacked", "ids": unacked[row["wt"]]})
    if questions:
        out.append({"kind": "questions", "open": questions})
    return out


def build_row(w: dict, ctx: dict) -> dict:
    path, wt = w["path"], "main" if w.get("is_main") else Path(w["path"]).name
    base = f"origin/{ctx['default']}" if not w.get("is_main") else "@{u}"
    current = current_plan(path)
    plan = src.plan_of(path, current)
    ci_branches = {ctx["default"]} if w.get("is_main") else {wt, f"land/{wt}"}
    runs = ctx["runs"]
    row = {
        "wt": wt, "is_main": bool(w.get("is_main")), "own": os.path.realpath(path) == ctx["own"],
        "foreman": None if w.get("is_main") else fl.foreman_of(path), "path": path, "branch": w.get("branch"), "plan": current,
        **{k: v for k, v in plan.items() if k != "plan_slug"},
        **agent_facts(ctx["agents"], path), **git_facts(path, base),
        "queue": queue_fact(ctx["queue"], path, wt),
        "ci": [{k: r[k] for k in ("workflow", "status", "branch", "url")} for r in runs if r["branch"] in ci_branches] if runs else [],
    }
    row["waits"] = waits_of(row, ctx["log"], ctx["asking"], ctx["unacked"], src.open_questions(path, plan["plan_slug"]))
    return row


def collect(repo: str, here: str | None = None) -> dict:
    """`here` is the folder the script runs in (default: the current folder): its checkout's row is the `own` one."""
    main = fl.main_checkout(repo)
    default = default_branch(main)
    log = src.farmer_log(main)
    with ThreadPoolExecutor(3) as pool:  # the three slow tools (gh about 4 s) at once
        f_agents, f_queue, f_runs = pool.submit(src.agents), pool.submit(src.queue, main), pool.submit(src.open_runs, main)
    runs = f_runs.result()
    top = src.git(here or os.getcwd(), "rev-parse", "--show-toplevel")
    ctx = {"own": os.path.realpath(top) if top else None, "default": default, "agents": f_agents.result(), "queue": f_queue.result(), "runs": runs, "log": log,
           "asking": src.asks(log), "unacked": src.unacked(log)}
    slots = [w for w in fl.worktrees(main) if not Path(w["path"]).name.startswith(".")]
    main_branch = src.git(main, "symbolic-ref", "--short", "-q", "HEAD")
    slots.append({"path": main, "branch": main_branch, "is_main": True})
    with ThreadPoolExecutor(POOL) as pool:
        rows = list(pool.map(lambda w: build_row(w, ctx), slots))
    rows.sort(key=slot_key)
    nested = arrange(rows)
    for r in rows:
        r["cells"] = state_table.cells(r, default, r["wt"] in nested)
    head = (src.git(main, "log", "-1", "--format=%H%x09%ct%x09%s", f"origin/{default}") or "").split("\t", 2)
    stamp = int(head[1]) if len(head) == 3 and head[1].isdigit() else None
    return {"repo": main, "default": default, "head": head[0][:8] or None if len(head) == 3 else None,
            "head_age": max(0, int(time.time()) - stamp) if stamp else None, "head_subject": head[2] if len(head) == 3 else None,
            "queue": ctx["queue"], "runs": runs, "rows": rows}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", default=os.getcwd(), help="a path inside the repository (default: the current folder)")
    p.add_argument("--json", action="store_true", help="the raw rows as JSON (each with its five `cells`) instead of the table")
    args = p.parse_args(argv)
    data = collect(args.repo)
    print(json.dumps(data, indent=2) if args.json else state_table.table(data))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
