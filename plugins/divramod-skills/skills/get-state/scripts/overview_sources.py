"""What the overview table (`overview.py`, hal2 plan 0591) reads: one facts dict per repository, every source read
only and None (or empty) when its tool is missing, fails or is slow, never an error (plan 0591 D3). The CLIs go through
`state_sources.tool`, the merge queue through `tollman_sources.raw_queue` (it keeps the hitched mark), the git facts
through `farmer_link`; nothing here is copied from them.
"""

import os
import re
import sys
from pathlib import Path

import farmer_link as fl
import state_sources as src
import tollman_sources

EFFORT_ARG = re.compile(r"--effort[ =](\S+)")
ROLE_PREFIXES = ("farmer-", "tollman-")


def is_claude(agent: dict) -> bool:
    return agent.get("kind") == "claude"


def fields(main: str) -> list[dict]:
    """The repository's linked worktrees as `{wt, path, lead}`: `lead` is the foreman's field its plans/LEAD names."""
    out = []
    for w in fl.worktrees(main):
        path = os.path.realpath(w["path"])
        out.append({"wt": Path(path).name, "path": path, "lead": fl.foreman_of(path)})
    return out


def repo_agents(by_path: dict | None, main: str, field_paths: set[str]) -> dict[str, dict]:
    """The live Claude sessions of the main checkout and the repository's fields, by real checkout path."""
    keep = field_paths | {os.path.realpath(main)}
    return {p: a for p, a in (by_path or {}).items() if p in keep and is_claude(a)}


def argv_efforts(agents: list[dict]) -> dict[str, str]:
    """`{pid: effort}` from the processes' `--effort` argument, for the agents whose `hal2-cli-agents` gives no
    `effort` (an older CLI): ONE `ps` call; empty when `ps` is missing (Windows) or fails."""
    pids = sorted({str(a["pid"]) for a in agents if not a.get("effort") and str(a.get("pid") or "").isdigit()})
    out = src.tool(["ps", "-o", "pid=", "-o", "args=", "-p", ",".join(pids)]) if pids else None
    found = {}
    for line in (out or "").splitlines():
        pid, _, args = line.strip().partition(" ")
        m = EFFORT_ARG.search(args)
        if pid in pids and m:
            found[pid] = m.group(1)
    return found


def timer(repo: str) -> str | None:
    """The tollman's timer `local.tollman.<repo>`: `enabled` when launchd has it loaded, else `disabled`; None off
    macOS or when `launchctl` gives nothing (shown as `-`, every-feature-on-windows-linux-and-macos)."""
    if sys.platform != "darwin":
        return None
    out = src.tool(["launchctl", "list"])
    if out is None:
        return None
    return "enabled" if re.search(rf"\slocal\.tollman\.{re.escape(repo)}\s*$", out, re.M) else "disabled"


def queue(main: str, repo: str) -> list[dict] | None:
    """The merge queue's tickets of this repository (a ticket without `repo` counts), None when unknown."""
    raw = tollman_sources.raw_queue(main)
    if raw is None:
        return None
    return [t for t in raw["queue"] if t.get("repo") in (None, repo)]


def questions(agents: dict[str, dict], field_list: list[dict]) -> dict[str, list[str]]:
    """The open question ids of each field's running plan (`plan_progress.slug`), by field name."""
    out = {}
    for f in field_list:
        slug = ((agents.get(f["path"]) or {}).get("plan_progress") or {}).get("slug")
        if slug:
            out[f["wt"]] = src.open_questions(f["path"], slug)
    return out


def facts(repo_path: str) -> dict:
    """Everything `overview.rows` needs for the repository holding `repo_path`."""
    main = os.path.realpath(fl.main_checkout(repo_path))
    repo = Path(main).name
    field_list = fields(main)
    by_path = src.agents()
    agents = repo_agents(by_path, main, {f["path"] for f in field_list})
    return {"repo": repo, "main": main, "agents_known": by_path is not None, "agents": agents, "fields": field_list,
            "queue": queue(main, repo), "asks": sorted(src.asks(src.farmer_log(main))),
            "questions": questions(agents, field_list), "argv_effort": argv_efforts(list(agents.values())),
            "timer": timer(repo)}
