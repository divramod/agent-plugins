#!/usr/bin/env python3
"""The state call, `/s` (hal2 plans 0268, 0366): one row per worktree of the repository, collected as code, no model.

    state.py [--repo <path>] [--role <role>] [--no-open] [--text | --json]

By default writes the session's role's page (role.py detects the role from the checkout of --repo, views.py builds
the page, page.py writes it to the state dir), opens it from the loopback server serve.py (reused or started, plan 0369
D1) and prints one line, its URL; without a server it opens the file and prints its path. --no-open only writes the
file and prints its path, starting nothing. --text prints the table (the own row's WT bold, a foreman's servants under its row as `↳ <WT>`) `WT | Plan | Steps | State | Waits for` and a line under it (state_table.py), or with --json
{repo, default, head, head_age, head_subject, queue, mode, runs, rows}: the raw facts per worktree (`wt`, `path`, `branch`, `plan` = the text of
plans/CURRENT_PLAN, `plan_number`, `plan_name`, `steps_done`, `steps_total`, `description` (the plan.md front matter's, or null), `own` the checkout the script runs in, `foreman` the worktree named by plans/LEAD (or null), `agent` busy|idle|none, `agent_state`,
`last_commit_age` seconds, `uncommitted`, `ahead` commits not on origin/<default> (the main checkout: not pushed),
`git` the statusline's numbers {behind, ahead, stash, untracked, added, modified, deleted} (or null), `done_pct` (or null), `queue`, `ci` the worktree's open runs, `waits` fact dicts, `cells` the five table cells). A fact that cannot be known is None (a missing, failing or
slow tool never raises). Rows: numbered worktrees by number, named worktrees by name, the main checkout last as `main`; dot
checkouts and prunable worktrees are no rows. Only reads: no fetch, no write.
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import farmer_link as fl
import ledger_sources
import page
import role as roles
import serve_launch
import state_sources as src
import state_table
import views

POOL = 11  # the three slow tools plus eight worktrees at a time
TABLE_FACTS = ("last_commit_age", "uncommitted", "ahead")  # what only the five-cell table (state_table.cells) shows


def slot_key(row: dict) -> tuple:
    name = row["wt"]
    if row["is_main"]:
        return (2, 0, name)
    return (0, int(name), name) if name.isdigit() else (1, 0, name)


def arrange(rows: list[dict]) -> set[str]:
    """Moves each servant (a worktree whose plans/LEAD names a foreman's worktree of this table) directly under its foreman's row,
    the servants of one foreman by number, in place; returns the worktrees that now stand nested."""
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


def train_branches(tickets: list[dict] | None, path: str, wt: str) -> set[str]:
    """The `land/train-...` branches the worktree's ticket lands on (the tollman's carrier, plan 0383 step 1): its
    runs are the worktree's, though the branch carries a train's name, not `land/<wt>`."""
    return {t["land_ref"] if t["land_ref"].startswith("land/") else f"land/{t['land_ref']}" for t in tickets or []
            if t.get("land_ref") and (t["worktree"] == os.path.realpath(path) or (t["worktree"] is None and t["slot"] == wt))}


def waits_of(row: dict, log: list[dict] | None, asking: set, unacked: dict, questions: list[str]) -> list[dict]:
    """The facts a worktree waits for, in a fixed order: the queue, a CI run, an open ask, unacked instructions, plan questions."""
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


def done_pct(done: int | None, total: int | None) -> int | None:
    """The done percentage of a plan's steps, rounded half up; None without steps."""
    return (200 * done + total) // (2 * total) if isinstance(done, int) and isinstance(total, int) and total > 0 else None


def worktree_facts(w: dict, default: str, table_facts: bool = True) -> dict:
    """The IO of one worktree's row: its plan, foreman, git facts (only with `table_facts`, else None each: their
    `git status` and two more git calls were 60% of a collect's time, D14), statusline numbers and open questions."""
    path = w["path"]
    base = f"origin/{default}" if not w.get("is_main") else "@{u}"
    current = current_plan(path)
    plan = src.plan_of(path, current)
    return {"plan": current, "plan_facts": plan, "foreman": None if w.get("is_main") else fl.foreman_of(path),
            "git_facts": git_facts(path, base) if table_facts else dict.fromkeys(TABLE_FACTS), "git": src.git_numbers(path),
            "questions": src.open_questions(path, plan["plan_slug"])}


def build_row(w: dict, ctx: dict, facts: dict | None = None) -> dict:
    """One worktree's row from its facts (`worktree_facts`, read here when not given) and the shared `ctx`."""
    f = facts or worktree_facts(w, ctx["default"])
    path, wt = w["path"], "main" if w.get("is_main") else Path(w["path"]).name
    ci_branches = {ctx["default"]} if w.get("is_main") else {wt, f"land/{wt}", *train_branches(ctx["queue"], path, wt)}
    runs = ctx["runs"]
    row = {
        "wt": wt, "is_main": bool(w.get("is_main")), "own": os.path.realpath(path) == ctx["own"],
        "foreman": f["foreman"], "path": path, "branch": w.get("branch"), "plan": f["plan"],
        **{k: v for k, v in f["plan_facts"].items() if k != "plan_slug"},
        **agent_facts(ctx["agents"], path), **f["git_facts"], "git": f["git"],
        "queue": queue_fact(ctx["queue"], path, wt),
        "ci": [{k: r[k] for k in ("workflow", "status", "branch", "url")} for r in runs if r["branch"] in ci_branches] if runs else [],
    }
    row["done_pct"] = done_pct(row["steps_done"], row["steps_total"])
    row["waits"] = waits_of(row, ctx["log"], ctx["asking"], ctx["unacked"], f["questions"])
    return row


def ledger_rows(slots: list[dict]) -> list[dict]:
    """What `ledger_sources` picks a plan's field by (wt, path, plan, foreman), read before the rows (two small files)."""
    return [{"wt": Path(w["path"]).name, "path": w["path"], "plan": current_plan(w["path"]),
             "foreman": fl.foreman_of(w["path"])} for w in slots if not w.get("is_main")]


def collect(repo: str, here: str | None = None, table_facts: bool = True, ledgers: bool = False) -> dict:
    """`here` is the folder the script runs in (default: the current folder): its checkout's row is the `own` one.
    One pool runs the slow tools (gh about 4 s, the agents about 2 s) beside every worktree's reads (plan 0369 D14);
    `table_facts=False` (a page without the five-cell table, `page_facts`) leaves `TABLE_FACTS` None; `ledgers` adds
    `questions` (`ledger_sources`, the CLI once per plan in the same pool, so it overlaps gh, D15)."""
    main = fl.main_checkout(repo)
    default = default_branch(main)
    slots = [w for w in fl.worktrees(main) if not Path(w["path"]).name.startswith(".")]
    slots.append({"path": main, "branch": src.git(main, "symbolic-ref", "--short", "-q", "HEAD"), "is_main": True})
    with ThreadPoolExecutor(POOL) as pool:
        f_agents, f_queue, f_runs = pool.submit(src.agents), pool.submit(src.queue_state, main), pool.submit(src.open_runs, main)
        f_jobs = pool.submit(src.workqueue_jobs)
        f_questions = ledger_sources.submit_questions(ledger_rows(slots), pool) if ledgers else None
        f_facts = [pool.submit(worktree_facts, w, default, table_facts) for w in slots]
        log = src.farmer_log(main)
        top = src.git(here or os.getcwd(), "rev-parse", "--show-toplevel")
        head = (src.git(main, "log", "-1", "--format=%H%x09%ct%x09%s", f"origin/{default}") or "").split("\t", 2)
        runs = f_runs.result()
        ctx = {"own": os.path.realpath(top) if top else None, "default": default, "agents": f_agents.result(), **f_queue.result(),
               "runs": runs, "log": log, "asking": src.asks(log), "unacked": src.unacked(log)}
        rows = [build_row(w, ctx, f.result()) for w, f in zip(slots, f_facts)]
        questions = f_questions() if f_questions else None
    rows.sort(key=slot_key)
    nested = arrange(rows)
    for r in rows:
        r["cells"] = state_table.cells(r, default, r["wt"] in nested)
    stamp = int(head[1]) if len(head) == 3 and head[1].isdigit() else None
    out = {"repo": main, "default": default, "head": head[0][:8] or None if len(head) == 3 else None,
           "head_age": max(0, int(time.time()) - stamp) if stamp else None, "head_subject": head[2] if len(head) == 3 else None,
           "queue": ctx["queue"], "mode": ctx["mode"], "runs": runs, "jobs": f_jobs.result(), "rows": rows}
    return {**out, "questions": questions} if ledgers else out


def page_facts(repo: str, override: str | None) -> dict:
    """`collect`'s options for the page of `repo`'s role: `table_facts` only for the five-cell table
    (`views.shows_cells`), `ledgers` only for the farmer's page (its questions table)."""
    role = roles.resolve(override, src.git(repo, "rev-parse", "--show-toplevel"), fl.main_checkout(repo))
    return {"table_facts": views.shows_cells(role), "ledgers": role == "farmer"}


def role_of(data: dict, repo: str, override: str | None) -> str:
    """The page's role: `--role`, else the one detected from the checkout of `repo`."""
    return roles.resolve(override, src.git(repo, "rev-parse", "--show-toplevel"), data["repo"])


def page_html(data: dict, repo: str, override: str | None) -> tuple[str, str]:
    """The role's page for the checkout of `repo`: its file name and its HTML (serve.py renders it fresh too)."""
    top = src.git(repo, "rev-parse", "--show-toplevel")
    main = data["repo"]
    role = roles.resolve(override, top, main)
    checkout = "main" if top and os.path.realpath(top) == os.path.realpath(main) else Path(top or repo).name
    ctx = {"repo": Path(main).name, "checkout": checkout, "top": top, "main": main}
    title, sections = views.build(role, data, ctx)
    return page.page_name(ctx["repo"], checkout, role), page.render(title, sections, state_table.line(data))


def show_page(data: dict, repo: str, override: str | None, open_it: bool) -> Path:
    """Writes the role's page for the checkout of `repo` (opened unless `open_it` is False) and returns its path."""
    path = page.write(*page_html(data, repo, override))
    if open_it:
        page.open_page(path)
    return path


def served(repo: str, override: str | None) -> str | None:
    """Opens the page from the loopback server (reused or started, D1) and returns its URL; None without a server."""
    port = serve_launch.ensure()
    if port is None:
        return None
    url = serve_launch.page_url(port, repo, override)
    serve_launch.open_url(url)
    return url


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", default=os.getcwd(), help="a path inside the repository (default: the current folder)")
    out = p.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true", help="the raw rows as JSON (each with its five `cells`) instead of the page")
    out.add_argument("--text", action="store_true", help="the table and the line under it instead of the page")
    p.add_argument("--role", choices=roles.ROLES, help="the page of this role instead of the detected one")
    p.add_argument("--no-open", action="store_true", help="write the page without opening it in the browser")
    args = p.parse_args(argv)
    if args.json or args.text:
        data = collect(args.repo)
        print(json.dumps(data, indent=2) if args.json else state_table.table(data))
        return 0
    url = None if args.no_open else served(args.repo, args.role)  # the server renders its own copy meanwhile
    data = collect(args.repo, **page_facts(args.repo, args.role))
    path = show_page(data, args.repo, args.role, open_it=not args.no_open and url is None)
    print(url or path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
