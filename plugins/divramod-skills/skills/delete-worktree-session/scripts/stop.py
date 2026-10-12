#!/usr/bin/env python3
"""Stop a running agent session of a repository's worktree; the worktree and its work stay.

  stop.py list [--repo DIR]                              the repository's running agent sessions
  stop.py stop <NN|%N|t:<id>> [--repo DIR] [--force] [--wait SECONDS]

`stop` ends the agent by signal, never by typing `/exit` (hal2 plan 0212: a typed `/exit` was not taken, its
"Exit and stop tasks" dialog and drafts left sessions running, 2026-10-08): `hal2-cli-agents stop <pane>` kills its
terminal host (`t:<id>`) or sends SIGHUP, SIGTERM, SIGKILL to its tmux pane's process group, and refuses a draft in
its box, running background tasks or a clear-and-continue job too; an older hal2 without `stop` cannot see a draft:
refused, with --force its host killed or its process signalled here. It waits --wait seconds (default 15) for the session to be gone. It refuses (exit 3,
`refused` names why) the session it runs in, a busy agent (working, starting, blocked) and a slot whose landing runs
or waits in the merge queue, unless --force (never for its own session). Exit 4: several sessions in that slot (name the pane). Prints
JSON. Exit 2 when a hal2 CLI is missing.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

BUSY = {"working", "starting", "blocked"}
GONE = {"ended", "failed"}


def die(message: str, code: int = 1) -> NoReturn:
    print(f"stop.py: {message}", file=sys.stderr)
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


def own_panes() -> set[str]:
    panes = {os.environ.get("TMUX_PANE", "")}
    if os.environ.get("HAL2_TERMINAL"):
        panes.add(f"t:{os.environ['HAL2_TERMINAL']}")
    return panes - {""}


def sessions(repo: Path) -> list[dict]:
    agents = json.loads(run("hal2-cli-agents", "list", "--json"))
    agents = agents if isinstance(agents, list) else agents.get("agents", [])
    keep = ("pane_id", "slot", "kind", "state", "title", "plan", "pid", "context_percent")
    mine = own_panes()
    return [{**{k: a.get(k) for k in keep}, "self": a.get("pane_id") in mine} for a in agents
            if a.get("project") and Path(a["project"]).resolve() == repo.resolve()
            and a.get("state") not in GONE]


def landing(repo: Path, slot: str) -> str | None:
    queue = json.loads(run("hal2-cli-git", "worktree", "queue", "--json", cwd=repo)).get("queue", [])
    for ticket in queue:
        if ticket.get("repo") == repo.name and ticket.get("slot") == slot and ticket.get("state") != "held":
            return ticket.get("state") or "queued"
    return None


def find(repo: Path, target: str) -> dict:
    live = sessions(repo)
    if target.startswith(("%", "t:")):
        found = [a for a in live if a["pane_id"] == target]
    else:
        found = [a for a in live if a["slot"] == target.zfill(2) or a["slot"] == target]
    if not found:
        die(f"no running agent session {target} in {repo.name}")
    if len(found) > 1:
        print(json.dumps({"ambiguous": found}, indent=2, ensure_ascii=False))
        sys.exit(4)
    return found[0]


def refusal(repo: Path, agent: dict, force: bool) -> str | None:
    if agent["self"]:
        return "this is the session running the skill"
    if force:
        return None
    if agent["state"] in BUSY:
        return f"the agent is {agent['state']}"
    state = landing(repo, agent["slot"])
    return f"its landing is {state} in the merge queue" if state else None


def still_running(repo: Path, pane: str) -> bool:
    return any(a["pane_id"] == pane for a in sessions(repo))


def wait_gone(repo: Path, pane: str, seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not still_running(repo, pane):
            return True
        time.sleep(0.5)
    return not still_running(repo, pane)


def hard_stop(agent: dict) -> str:
    """The stop of an older hal2 without `hal2-cli-agents stop`: the host's kill, else SIGHUP, SIGTERM, SIGKILL."""
    pane, pid = agent["pane_id"], agent.get("pid")
    if pane.startswith("t:"):
        run("hal2-cli-agents", "terminal", "kill", pane[2:])
        return "terminal-kill"
    if not pid:
        die(f"{pane} has no pid to signal")
    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(int(pid), sig)
        except ProcessLookupError:
            break
        time.sleep(3)
    return "signal"


def hal2_stop(agent: dict, force: bool) -> str | None:
    """`hal2-cli-agents stop`: how it stopped; exit 3 when hal2 refused; None when hal2 has no `stop` yet."""
    if not shutil.which("hal2-cli-agents"):
        die("hal2-cli-agents is missing: run scripts/install-prerequisites.sh (needs hal2)", 2)
    args = ["hal2-cli-agents", "stop", agent["pane_id"], "--json"] + (["--force"] if force else [])
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode == 2 and "unknown command" in r.stderr:
        return None
    if r.returncode == 3:
        refused = json.loads(r.stdout or "{}").get("refused") or r.stderr.strip()
        print(json.dumps({"refused": refused, "session": agent}, indent=2, ensure_ascii=False))
        sys.exit(3)
    if r.returncode:
        die(f"hal2-cli-agents stop {agent['pane_id']} failed: {(r.stderr or r.stdout).strip()}")
    return json.loads(r.stdout)["how"]


def cmd_stop(repo: Path, target: str, force: bool, wait: float) -> dict:
    agent = find(repo, target)
    why = refusal(repo, agent, force)
    if why:
        print(json.dumps({"refused": why, "session": agent}, indent=2, ensure_ascii=False))
        sys.exit(3)
    pane = agent["pane_id"]
    how = hal2_stop(agent, force)
    if how is None and not force:
        print(json.dumps({"refused": "this hal2 has no `hal2-cli-agents stop` to check the box for a draft: install "
                          "hal2 (plan 0212) or --force", "session": agent}, indent=2, ensure_ascii=False))
        sys.exit(3)
    how = how or hard_stop(agent)
    if not wait_gone(repo, pane, wait):
        die(f"{pane} is still running after {how}")
    return {"stopped": pane, "slot": agent["slot"], "how": how, "plan": agent.get("plan")}


def arg(argv: list[str], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    repo = main_checkout(Path(arg(argv, "--repo") or ".").expanduser().resolve())
    if argv[0] == "list":
        result = sessions(repo)
    elif argv[0] == "stop" and len(argv) > 1:
        result = cmd_stop(repo, argv[1], "--force" in argv, float(arg(argv, "--wait") or 15))
    else:
        die("usage: stop.py list | stop <NN|%N|t:<id>> [--force] [--wait SECONDS]")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
