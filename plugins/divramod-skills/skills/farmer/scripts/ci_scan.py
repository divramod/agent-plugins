#!/usr/bin/env python3
"""The state of a repository's GitHub Actions, for the farmer skill's ci duty.

  ci_scan.py scan [--repo <dir>] [--json] [--all]
      the latest run of every workflow (dynamic ones such as Dependabot's included) on the default branch and on each worktree branch,
      and findings: a workflow red on the default branch (with its failed jobs), red on
      a worktree's branch, a run queued too long (a runner offline?) or running too long (with `ending`: its own
      fail fast is stopping it, never cancel it by hand).
      Runs already handled are left out (--all: shown too). No workflows: nothing to do
  ci_scan.py record <run-id> <what> [--note <text>] [--repo <dir>]
      mark a run handled (log: ci.jsonl in the farmer's state folder)

Reads gh (gh run list, gh run view) and git; writes only the farmer's state folder (roles/farmer/ of its worktree).
Exit 0 on success, 2 when a tool is missing.
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import gh_runs
import mtm_ci
import pass_timing
import roles

DATA = roles.OVERRIDE  # FARMER_DIR's root, else None: the farmer's worktree's roles/farmer/ (roles.state_dir)
MINUTE = 60
# A run queued this long is reported (`queued-long`); the farmer wakes no runner: hal2's CI supervisor
# (hal2-daemon's role on the Mac, plan 0349 D83) is the one system that wakes and parks the CI machines.
QUEUED_TOO_LONG = 20 * MINUTE
QUEUED = ("queued", "waiting", "pending", "requested")
RUNNING_TOO_LONG = 90 * MINUTE
RED = {"failure", "timed_out", "startup_failure", "action_required"}
FIELDS = "databaseId,workflowName,status,conclusion,headBranch,headSha,createdAt,updatedAt,url,event"


def run(args: list[str], cwd: str | None = None) -> str:
    pass_timing.count_gh(args)
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def run_json(args: list[str], cwd: str | None = None):
    out = run(args, cwd)
    try:
        return json.loads(out) if out.strip() else None
    except json.JSONDecodeError:
        return None


def parse_time(text: str | None) -> float:
    try:
        return dt.datetime.fromisoformat((text or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def main_checkout(repo: str) -> str:
    common = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], repo).strip()
    return str(Path(common).parent) if common else repo


def is_slot_branch(branch: str) -> bool:
    return bool(re.fullmatch(r"\d\d", branch or ""))


def latest_runs(runs: list[dict], default: str) -> list[dict]:
    """The newest run per (workflow, branch), for the default branch and worktree branches."""
    seen, out = set(), []
    for r in sorted(runs, key=lambda r: parse_time(r.get("createdAt")), reverse=True):
        branch = r.get("headBranch") or ""
        if branch != default and not is_slot_branch(branch):
            continue
        key = (r.get("workflowName"), branch)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def findings(latest: list[dict], default: str, now: float, done: set[int]) -> list[dict]:
    out = []
    for r in latest:
        rid, status, conclusion = r.get("databaseId"), r.get("status"), r.get("conclusion")
        branch, name = r.get("headBranch"), r.get("workflowName")
        age = now - parse_time(r.get("createdAt"))
        base = {"run": rid, "workflow": name, "branch": branch, "url": r.get("url"), "sha": (r.get("headSha") or "")[:8],
                "handled": rid in done}
        if status == "completed" and conclusion in RED:
            kind = "main-red" if branch == default else "slot-red"
            out.append({**base, "kind": kind, "why": f"{name} {conclusion} on {branch}"})
        elif status in QUEUED and age > QUEUED_TOO_LONG:
            out.append({**base, "kind": "queued-long", "why": f"{name} queued {int(age // 60)} min on {branch}: a runner offline?"})
        elif status == "in_progress" and age > RUNNING_TOO_LONG:
            out.append({**base, "kind": "running-long", "why": f"{name} running {int(age // 60)} min on {branch}"})
    order = {"main-red": 0, "queued-long": 1, "running-long": 2, "slot-red": 3}
    return sorted(out, key=lambda f: order[f["kind"]])


def failed_jobs(jobs: list[dict]) -> list[str]:
    """`<job>: <its first failed step>` of a run's red jobs."""
    return [f"{j.get('name')}: {next((s.get('name') for s in j.get('steps') or [] if s.get('conclusion') == 'failure'), '?')}"
            for j in jobs or [] if j.get("conclusion") in RED]


def stuck(finding: dict, jobs: list[dict]) -> dict:
    """A running-long finding with what its jobs say of a cancel by hand: `ending` (mtm_ci.ending: a job of the gate
    concluded `cancelled`, or a stop step ended `success` or still runs) is a run nobody asks to cancel."""
    finding["ending"] = mtm_ci.ending(jobs)
    if finding["ending"]:
        finding["why"] += ": its own fail fast is ending it, never cancel it"
    return finding


def handled(main: str) -> set[int]:
    f = roles.state_dir(main, DATA) / "ci.jsonl"
    if not f.exists():
        return set()
    return {int(e["run"]) for e in map(json.loads, f.read_text().splitlines())}


def scan(repo: str, show_all: bool) -> dict:
    main = main_checkout(repo)
    runs = gh_runs.listed(run_json, ["gh", "run", "list", "--limit", "100", "--json", FIELDS], main) or []
    if not runs and not any((Path(main) / ".github/workflows").glob("*.y*ml")):
        return {"repo": main, "workflows": False, "findings": []}
    default = (run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], main).strip()
               .removeprefix("origin/") or "main")
    found = findings(latest_runs(runs, default), default, time.time(), handled(main))
    if not show_all:
        found = [f for f in found if not f["handled"]]
    red = [f for f in found if f["kind"].endswith("-red")]
    long = [f for f in found if f["kind"] == "running-long"]
    jobs = gh_runs.jobs([f["run"] for f in red + long], {f["run"] for f in red}, gh_runs.view_jobs(run_json, main))
    for f in red:  # a red run is completed: its jobs are kept on disk (gh_runs)
        f["failed_jobs"] = failed_jobs(jobs.get(f["run"], []))
    for f in long:  # a running run's jobs are read again every round
        stuck(f, jobs.get(f["run"], []))
    return {"repo": main, "workflows": True, "default": default, "findings": found}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--repo", default=os.getcwd())
    s.add_argument("--json", action="store_true")
    s.add_argument("--all", action="store_true")
    r = sub.add_parser("record")
    r.add_argument("run", type=int)
    r.add_argument("what")
    r.add_argument("--note", default="")
    r.add_argument("--repo", default=os.getcwd())
    args = p.parse_args(argv)
    if not shutil.which("gh") or not shutil.which("git"):
        print("ci_scan.py: missing gh or git; run install-prerequisites.sh", file=sys.stderr)
        return 2
    if args.cmd == "scan":
        result = scan(args.repo, args.all)
        if args.json:
            print(json.dumps(result, indent=1))
        elif not result["workflows"]:
            print("no GitHub Actions workflows: nothing to watch")
        else:
            for f in result["findings"]:
                print(f"- {f['kind']:12} {f['why']}  {f['url']}")
                for job in f.get("failed_jobs", []):
                    print(f"    {job}")
            if not result["findings"]:
                print("CI green")
    else:
        d = roles.state_dir(args.repo, DATA)
        with (d / "ci.jsonl").open("a") as f:
            f.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "run": args.run,
                                "what": args.what, "note": args.note}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
