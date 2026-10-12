#!/usr/bin/env python3
"""List a repository's free worktrees: a running agent session that does no work.

  free.py [--repo DIR] [--all]

A worktree slot is free when an agent session runs in it, none of its agents is busy (working, starting,
blocked) and it holds no work: plans/CURRENT_PLAN names nothing, no uncommitted changes, no commits not merged
into main, no landing of it running, waiting or holding the merge queue. Being behind main is fine (/mfm).
--all lists every worktree slot with the reason it is not free. Prints JSON. Exit 2 when a hal2 CLI is missing.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

BUSY = {"working", "starting", "blocked"}
GONE = {"ended", "failed"}


def die(message: str, code: int = 1) -> NoReturn:
    print(f"free.py: {message}", file=sys.stderr)
    sys.exit(code)


def run(*args: str, cwd: Path | None = None) -> str:
    if not shutil.which(args[0]):
        die(f"{args[0]} is missing: run scripts/install-prerequisites.sh (needs hal2)", 2)
    r = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        die(f"{' '.join(args[:3])} failed: {(r.stderr or r.stdout).strip()}")
    return r.stdout


def main_checkout(repo: Path) -> Path:
    out = run("git", "worktree", "list", "--porcelain", cwd=repo)
    first = out.splitlines()[0] if out else ""
    return Path(first.split(" ", 1)[1]) if first.startswith("worktree ") else repo


def agents_by_slot(repo: Path) -> dict[str, list[dict]]:
    agents = json.loads(run("hal2-cli-agents", "list", "--json"))
    agents = agents if isinstance(agents, list) else agents.get("agents", [])
    slots: dict[str, list[dict]] = {}
    for a in agents:
        if a.get("project") and Path(a["project"]).resolve() == repo.resolve() and a.get("state") not in GONE:
            slots.setdefault(a.get("slot") or "main", []).append(a)
    return slots


def queued(repo: Path) -> dict[str, str]:
    queue = json.loads(run("hal2-cli-git", "worktree", "queue", "--json", cwd=repo)).get("queue", [])
    return {t["slot"]: t.get("state") or "queued" for t in queue if t.get("repo") == repo.name and t.get("slot")}


def why_not_free(agents: list[dict], w: dict, landing: str | None) -> str | None:
    if not agents:
        return "no session running"
    busy = [a["state"] for a in agents if a.get("state") in BUSY]
    if busy:
        return f"the agent is {busy[0]}"
    if w.get("plan"):
        return f"works on {w['plan']}"
    if w.get("dirty"):
        return "uncommitted changes"
    if w.get("main_ahead"):
        return f"{w['main_ahead']} commit{'s' if w['main_ahead'] != 1 else ''} not on main"
    if landing:
        return f"its landing is {landing} in the merge queue"
    return None


def rows(repo: Path) -> list[dict]:
    listed = json.loads(run("hal2-cli-git", "worktree", "list", "--json", cwd=repo)).get("worktrees", [])
    slots, queue = agents_by_slot(repo), queued(repo)
    out = []
    for w in listed:
        if w.get("main"):
            continue
        slot, agents = w["name"], slots.get(w["name"], [])
        why = why_not_free(agents, w, queue.get(w["name"]))
        out.append({
            "slot": slot,
            "free": why is None,
            "why": why,
            "panes": [a["pane_id"] for a in agents],
            "state": agents[0]["state"] if agents else None,
            "plan": w.get("plan"),
            "behind_main": w.get("main_behind", 0),
            "context_percent": agents[0].get("context_percent") if agents else None,
            "worktree": w.get("path"),
        })
    return out


def arg(argv: list[str], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    repo = main_checkout(Path(arg(argv, "--repo") or ".").expanduser().resolve())
    result = rows(repo)
    if "--all" not in argv:
        result = [r for r in result if r["free"]]
    print(json.dumps({"repo": repo.name, "worktrees": result}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
