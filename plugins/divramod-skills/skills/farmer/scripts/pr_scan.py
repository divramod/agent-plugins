#!/usr/bin/env python3
"""A repository's open pull requests, for the farmer skill's prs duty: the list stays clean.

  pr_scan.py scan [--repo <dir>] [--json]
      every open pull request by kind, and findings:
        dependabot   the open Dependabot PRs, as one batch (one servant applies them all)
        superseded   a Dependabot PR main already holds (merging it changes nothing): closed by the tick
        land-stale   a landing's PR (land/<slot>) whose slot has no ticket in the merge queue for a day;
                     `ahead` says how many commits the slot still holds beyond main
        other        any other open PR (a person's, an app's): the user's to decide

Reads gh (gh pr list), git and hal2-cli-git; writes nothing.
Exit 0 on success, 2 when a tool is missing.
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from ci_scan import main_checkout, parse_time, run, run_json

FIELDS = "number,title,author,headRefName,headRefOid,createdAt,updatedAt,url,isDraft"
STALE = 24 * 3600  # a landing PR without a queue ticket this long is left over
LAND = re.compile(r"land/(.+)")


def kind_of(pr: dict) -> str:
    head, login = pr.get("headRefName") or "", (pr.get("author") or {}).get("login") or ""
    if head.startswith("dependabot/") or login in ("app/dependabot", "dependabot[bot]", "dependabot"):
        return "dependabot"
    return "landing" if LAND.fullmatch(head) else "other"


def brief_pr(pr: dict) -> dict:
    return {"number": pr["number"], "title": pr.get("title", ""), "head": pr.get("headRefName", ""),
            "url": pr.get("url", ""), "created": pr.get("createdAt", "")}


def findings(prs: list[dict], queued: set[str], superseded: set[int], ahead: dict[str, int], now: float) -> list[dict]:
    """The findings of the open PRs. `queued`: slots with a merge-queue ticket; `superseded`: Dependabot PRs main
    already holds; `ahead`: commits each slot holds beyond main (absent: no such slot)."""
    out, deps = [], []
    for pr in sorted(prs, key=lambda p: p["number"]):
        kind, base = kind_of(pr), brief_pr(pr)
        if kind == "dependabot":
            if pr["number"] in superseded:
                out.append({**base, "kind": "superseded", "why": f"#{pr['number']} is already on main"})
            else:
                deps.append(base)
        elif kind == "landing":
            slot = LAND.fullmatch(pr["headRefName"]).group(1)
            idle = now - parse_time(pr.get("updatedAt"))
            if slot not in queued and idle > STALE:
                out.append({**base, "kind": "land-stale", "slot": slot, "ahead": ahead.get(slot, 0),
                            "why": f"#{pr['number']} (land/{slot}) has no queue ticket for {int(idle // 3600)} h"})
        elif not pr.get("isDraft"):
            out.append({**base, "kind": "other", "why": f"#{pr['number']} {pr.get('title', '')}"})
    if deps:
        nums = ", ".join(f"#{d['number']}" for d in deps)
        out.insert(0, {"kind": "dependabot", "prs": deps, "numbers": [d["number"] for d in deps],
                       "why": f"{len(deps)} open Dependabot PR(s): {nums}"})
    return out


def holds(main: str, head: str) -> bool:
    """Whether main already holds the PR: merging its head into origin/main leaves main's tree as it is."""
    tree = run(["git", "merge-tree", "--write-tree", "origin/HEAD", f"origin/{head}"], main).split("\n", 1)[0].strip()
    return bool(tree) and tree == run(["git", "rev-parse", "origin/HEAD^{tree}"], main).strip()


def slot_ahead(main: str) -> dict[str, int]:
    root = Path.home() / ".hal/git/worktree" / Path(main).name
    out = {}
    for path in root.glob("*") if root.is_dir() else []:
        count = run(["git", "rev-list", "--count", "origin/HEAD..HEAD"], str(path)).strip()
        if count.isdigit():
            out[path.name] = int(count)
    return out


def scan(repo: str) -> dict:
    main = main_checkout(repo)
    prs = run_json(["gh", "pr", "list", "--state", "open", "--limit", "200", "--json", FIELDS], main)
    if prs is None:
        return {"repo": main, "ok": False, "prs": [], "findings": [], "why": "gh pr list failed"}
    deps = [p for p in prs if kind_of(p) == "dependabot"]
    if deps:
        run(["git", "fetch", "-q", "origin"] + [p["headRefName"] for p in deps], main)
    queue = run_json(["hal2-cli-git", "worktree", "queue", "--json"], main) or {}
    queued = {t.get("slot") for t in queue.get("queue", [])}
    superseded = {p["number"] for p in deps if holds(main, p["headRefName"])}
    lands = any(kind_of(p) == "landing" for p in prs)
    found = findings(prs, queued, superseded, slot_ahead(main) if lands else {}, time.time())
    return {"repo": main, "ok": True, "prs": [{**brief_pr(p), "kind": kind_of(p)} for p in prs], "findings": found}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--repo", default=os.getcwd())
    s.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    missing = [t for t in ("gh", "git", "hal2-cli-git") if not shutil.which(t)]
    if missing:
        print(f"pr_scan.py: missing {', '.join(missing)}; run install-prerequisites.sh", file=sys.stderr)
        return 2
    result = scan(args.repo)
    if args.json:
        print(json.dumps(result, indent=1))
    elif not result["ok"]:
        print(result["why"])
    else:
        for f in result["findings"]:
            print(f"- {f['kind']:11} {f['why']}")
        if not result["findings"]:
            print(f"{len(result['prs'])} open PR(s), nothing to clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
