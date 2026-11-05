#!/usr/bin/env python3
"""The wagons of the standing train and the hitched riders, one table row each (hal2 plan 0604 step 7, D11; L225, L228).

  tollman.py wagons [--no-fetch] [--json] [--repo <dir>]      (this script runs the same: wagons.py [...])

Columns: wt | plan | name | steps | status. The status is computed on every run from the facts of `wagons.jsonl`
(wagon_store.py) and git, never stored (wagon_status.py): entering (an order out), ready (answered, its commit waits for
the tollman's merge), boarded (every commit of it in the carrier), hitched (no order, not in it). The carrier is the
newest train's `train-<n>-<run>` (run_names.py; the run is the attempt of its last land ref), else the branch its
formed line names (a train formed before plan 0604). The duty `wagons` (wagons_duty.py) prints the table into the
tick's output every 20 minutes, no model call.

A run reads and writes only the tollman's state folder (the store, `wagons-last.json`); git and the queue are read, a
fetch of origin is the only write, and `--no-fetch` skips it.
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import bounded
import mtm_scan
import run_names
import wagon_store
from wagon_status import status as wagon_status

HTTPS = {  # the retry of a fetch whose ssh died: https with gh's credentials
    "GIT_CONFIG_COUNT": "3",
    "GIT_CONFIG_KEY_0": "url.https://github.com/.insteadOf", "GIT_CONFIG_VALUE_0": "git@github.com:",
    "GIT_CONFIG_KEY_1": "credential.helper", "GIT_CONFIG_VALUE_1": "",
    "GIT_CONFIG_KEY_2": "credential.helper", "GIT_CONFIG_VALUE_2": "!gh auth git-credential",
}
LAST = "wagons-last.json"  # the previous run's time and counts, in the state folder
KINDS = ("entering", "ready", "boarded", "hitched")
STATES = ("formed", "resolving", "resolved", "started", "run", "red", "order", "fixed", "retry", "landed")


def git(repo, *args, https=False) -> subprocess.CompletedProcess:
    """`git -C repo ...`, bounded; a program that cannot start or runs out is a failed call (127)."""
    argv = ["git", "-C", str(repo), *args]
    try:
        return bounded.run(argv, env={**os.environ, **HTTPS} if https else None)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(argv, 127, "", str(e))


def fetch(repo, *refs) -> int:
    """`git fetch origin <refs>`, once more over https when ssh failed."""
    code = git(repo, "fetch", "-q", "origin", *refs).returncode
    return code if code == 0 else git(repo, "fetch", "-q", "origin", *refs, https=True).returncode


def train_record(state: Path) -> dict | None:
    """The newest train as `train.jsonl` says: its last line, cars, carrier branch, the systematic carrier name
    `train-<number>-<run>` (the run: the attempt of its last `started` land ref, else 1) and its state."""
    f = state / "train.jsonl"
    recs = []
    for line in f.read_text().splitlines() if f.exists() else []:
        try:
            recs.append(json.loads(line))
        except ValueError:
            continue
    recs = [r for r in recs if isinstance(r, dict)]
    last = next((r for r in reversed(recs) if r.get("train")), None)
    if not last:
        return None
    mine = [r for r in recs if r.get("train") == last["train"]]
    # the carrier's branch is the formed line's (a later line may name a resolve branch)
    formed = next((r for r in reversed(mine) if r.get("kind") == "formed"), last)
    number = next((r["number"] for r in reversed(mine) if r.get("number")), None)
    run = 1
    for r in mine:
        m = re.fullmatch(r"train-(\d+)-(\d+)", str(r.get("land_ref", "")))
        if r.get("kind") == "started" and m:
            number, run = (int(m.group(1)) if number is None else number), int(m.group(2))
    return {"last": last, "train": last["train"], "cars": last["train"].split("@")[0].split("+"),
            "carrier": formed.get("branch") or formed.get("slot") or "", "number": number, "run": run,
            "name": run_names.carrier_name(number, run) if number else "",
            "state": next((r["kind"] for r in reversed(mine) if r["kind"] in STATES), "?"),
            "roles": next((r for r in reversed(mine) if r.get("kind") == "roles"), {})}


def fix_heads(repo, n: int, a: int) -> dict:
    """field -> (sha, UTC time) of origin/<NN>-train-<n>-<a>-fix (run_names.py), one ls-remote.

    A legacy origin/<NN>-train-fix counts only when its field has no standard branch (train 51's cutover)."""
    out = bounded.run(["git", "-C", str(repo), "ls-remote", "origin", "refs/heads/*-fix"]).stdout
    std, old = {}, {}
    for line in out.splitlines():
        sha, _, ref = line.partition("\t")
        name = ref.removeprefix("refs/heads/")
        p = run_names.parse(name)
        if p and p["kind"] == "fix" and (p["n"], p["a"]) == (n, a):
            std[p["field"]] = sha
        elif name.endswith("-train-fix") and name[:2].isdigit():
            old[name[:2]] = sha
    heads = {}
    for f, sha in {**old, **std}.items():
        if git(repo, "cat-file", "-e", sha).returncode:
            fetch(repo, sha)
        t = git(repo, "show", "-s", "--format=%ct", sha).stdout.strip()
        if t.isdigit():
            at = dt.datetime.fromtimestamp(int(t), dt.timezone.utc)
            heads[f] = (sha, at.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return heads


def carrier_check(repo, head: str):
    """in_carrier(sha): True/False by git, None when the commit is unknown here (fetched once)."""
    seen, fetched = {}, []

    def known(sha):
        return git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0

    def check(sha):
        if sha not in seen:
            if not known(sha) and not fetched:
                fetched.append(fetch(repo))
            seen[sha] = (git(repo, "merge-base", "--is-ancestor", sha, head).returncode == 0) if known(sha) else None
        return seen[sha]
    return check


def queue(repo) -> dict:
    """worktree -> the head of its ready mark, from the merge queue; a failed ask is an empty queue."""
    try:
        p = bounded.run(["hal2-cli-git", "worktree", "queue", "--json"], cwd=str(repo))
        d = json.loads(p.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}
    rows = d.get("entries", d.get("queue", []))
    return {str(e["slot"]): (e.get("ready") or {}).get("head") for e in rows if e.get("ready")}


def plan_of(root: Path | None) -> tuple[str, str, str]:
    """(plan number, title, `done/total` steps) of the plan a field's CURRENT_PLAN names; `-` where there is none."""
    ptr = root / "plans" / "CURRENT_PLAN" if root else None
    slug = ptr.read_text().strip() if ptr and ptr.exists() else ""
    if not re.match(r"^\d{4}-", slug):
        return slug or "-", "-", "-"
    pdir = root / "plans" / slug
    title, done, total = slug[5:], 0, 0
    md = pdir / "plan.md"
    if md.exists():
        text = md.read_text()
        m = re.search(r"^#\s+(.+)$", text, re.M)
        if m:
            title = re.sub(r"^(Plan\s+)?\d{4}[:\s-]*", "", m.group(1)).strip() or title
        for row in re.findall(r"^\|\s*\d+(?:\.\d+)?\s*\|.*\|\s*([^|]*?)\s*\|\s*$", text, re.M):
            total += 1
            done += row.lower().startswith("done")
    if total == 0:  # schema 2: steps/step-NN.md under subplans
        for st in pdir.glob("subplans/*/steps/step-*.md"):
            total += 1
            done += bool(re.search(r"^status:\s*done", st.read_text(), re.M | re.I))
    return slug[:4], title, f"{done}/{total}" if total else "-"


def field_roots(main: str) -> dict[str, Path]:
    """Worktree folder name -> path, from git (no literal path)."""
    return {Path(w["path"]).name: Path(w["path"]) for w in mtm_scan.worktrees(main)}


def collect(repo, state: Path, *, do_fetch: bool = True, ask_queue=queue) -> dict:
    """The table as data: carrier, state and a row per wagon (`wt, plan, name, steps, status, detail`)."""
    t = train_record(state)
    if not t:
        return {"carrier": None, "rows": [], "counts": dict.fromkeys(KINDS, 0)}
    names = [n for n in (t["name"], t["carrier"]) if n]
    for n in names if do_fetch else []:
        fetch(repo, n)
    std = git(repo, "rev-parse", "-q", "--verify", f"origin/{t['name']}").stdout.strip() if t["name"] else ""
    head = std or git(repo, "rev-parse", f"origin/{t['carrier']}").stdout.strip()
    hitched = ask_queue(repo)
    entering = t["last"]["field"] if t["last"].get("kind") == "resolving" else None
    order = t["cars"] + [s for s in hitched if s not in t["cars"]]
    formed = t["train"].split("@")[1] if "@" in t["train"] else ""
    store = state / wagon_store.STORE_NAME
    wagon_store.ingest(store, state / "log.jsonl", state / "train.jsonl")
    facts = [r for r in wagon_store.facts(store) if r.get("at", "") >= formed]
    in_carrier, memo, roots = carrier_check(repo, head), [], field_roots(mtm_scan.main_checkout(str(repo)))
    tn = run_names.parse(t["name"]) or {"n": 0, "a": 0}

    def fix_head(f):  # one ls-remote per run, only when a done ack named no sha
        if not memo:
            memo.append(fix_heads(repo, tn["n"], tn["a"]) if do_fetch else {})
        return memo[0].get(f)
    rows = []
    for f in order:
        st, detail = wagon_status(f, [r for r in facts if r["field"] == f], is_car=f in t["cars"],
                                  queue_head=hitched.get(f), in_carrier=in_carrier, fix_head=fix_head,
                                  resolving=f == entering)
        num, name, steps = plan_of(roots.get(f))
        rows.append({"wt": f, "plan": num, "name": name, "steps": steps, "status": st, "detail": detail})
    rows += role_rows(t["roles"], in_carrier)
    counts = {k: sum(r["status"] == k for r in rows) for k in KINDS}
    return {"carrier": t["name"] or t["carrier"], "head": head, "state": t["state"], "rows": rows, "counts": counts,
            "engine_branch": t["carrier"] if t["name"] and t["carrier"] != t["name"] else ""}


def role_rows(line: dict, in_carrier) -> list[dict]:
    """The role cars at the train's end (role_cars.py, plan 0604 D8): boarded by git, a left one `left <why>`."""
    rows = [{"wt": c["field"], "plan": "-", "name": f"the {c.get('role')}'s own commits", "steps": "-",
             "status": "boarded" if in_carrier(c["head"]) is True else "ready", "detail": "role car"}
            for c in line.get("cars") or []]
    return rows + [{"wt": c["field"], "plan": "-", "name": f"the {c.get('role')}'s own commits", "steps": "-",
                    "status": "left", "detail": str(c.get("why", ""))[:80]} for c in line.get("left") or []]


def sums(table: dict) -> dict:
    rows = table["rows"]
    pairs = [tuple(int(x) for x in r["steps"].split("/")) for r in rows if "/" in r["steps"]]
    return {"wagons": len(rows), "plans": sum(r["plan"].isdigit() for r in rows),
            "done": sum(p[0] for p in pairs), "total": sum(p[1] for p in pairs)}


def render(table: dict, prev: dict, now: str, off_standard: list[str] | None) -> str:
    """The table as the Markdown the tick prints."""
    if not table["carrier"]:
        return "no train yet: no wagons"
    legacy = f" (the engine's branch: {table['engine_branch']})" if table["engine_branch"] else ""
    out = [f"carrier {table['carrier']} at {table['head'][:10]} ({table['state']}){legacy}",
           "| wt | plan | name | steps | status |", "|---|---|---|---|---|"]
    out += [f"| {r['wt']} | {r['plan']} | {r['name']} | {r['steps']} | {(r['status'] + ' ' + r['detail']).strip()} |"
            for r in table["rows"]]
    s, c = sums(table), table["counts"]
    out.append(f"| **sum: {s['wagons']} wagons** | **{s['plans']} plans** | | **{s['done']}/{s['total']}** | **"
               + ", ".join(f"{c[k]} {k}" for k in KINDS) + "** |")
    delta = c["boarded"] - prev.get("boarded", c["boarded"])
    out += ["", f"prev run: {prev.get('at', '-')}; current run: {now} (boarded {delta:+d} since the prev run)",
            "names: not checked (--no-fetch)" if off_standard is None
            else f"names: {len(off_standard)} off-standard (run_names.py's off_standard lists them)" if off_standard
            else "names: all standard"]
    return "\n".join(out)


def last(state: Path) -> dict:
    try:
        return json.loads((state / LAST).read_text())
    except (OSError, ValueError):
        return {}


def save_last(state: Path, data: dict) -> None:
    tmp = state / f"{LAST}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(data))
    os.replace(tmp, state / LAST)  # atomic: a reader never sees half a file


def run(repo, *, do_fetch: bool = True, as_json: bool = False, state: Path | None = None) -> str:
    """One run: the table text (or JSON), the counts saved for the next run's delta."""
    state = state or wagon_store.folder(repo)
    table = collect(repo, state, do_fetch=do_fetch)
    prev, now = last(state), dt.datetime.now().strftime("%H:%M")
    bad = run_names.off_standard(run_names.repo_names(repo)) if table["carrier"] and do_fetch else None
    if table["carrier"]:
        save_last(state, {"at": now, **table["counts"]})
    if as_json:
        return json.dumps({"schema": 1, **table, "sum": sums(table), "prev": prev, "off_standard": bad}, indent=1,
                          default=str)
    return render(table, prev, now, bad)


def add_arguments(p: argparse.ArgumentParser, repo: bool = True) -> None:
    """The verb's options (`repo` False: tollman.py adds --repo to every command itself)."""
    p.add_argument("--no-fetch", action="store_true", help="read origin as fetched before")
    p.add_argument("--json", action="store_true")
    if repo:
        p.add_argument("--repo", default=os.getcwd())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(p)
    a = p.parse_args(argv)
    print(run(a.repo, do_fetch=not a.no_fetch, as_json=a.json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
