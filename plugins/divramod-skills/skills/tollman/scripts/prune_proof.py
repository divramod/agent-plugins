"""The prune duty's proof that a field holds nothing unsaved (the global record never-delete-unsaved-work; hal2 plan
0143, moved from the farmer to the tollman by plan 0360 step 7, D30, D67).

A field is free when nothing in it is unsaved: no commit (its branch or a side branch `NN-*`) that origin's default
branch lacks, no change, no plans/CURRENT_PLAN, no merge queue ticket or boss pause, no busy agent (working,
starting, blocked), no session active in the last 30 minutes (10-99), no build running in it (cleanup's `busy`) and no
open question to the user (the tollman's log and the farmer's). A field marked `plans/LEAD` (a servant's) is measured
against its foreman's branch instead (`subservant_refusal`). Never main, a role field or a name that is not two digits.
"""

import re
import subprocess
import sys
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import lead_marker
import logstate
import mtm_scan
import tick
from skillpath import sibling

CLEANUP = sibling("cleanup") / "scripts/cleanup.py"
NUMBERED = re.compile(r"\d\d")
BUSY = {"working", "starting", "blocked"}
GONE = {"ended", "failed"}
QUIET = 30 * 60  # a 10-99 session active more recently is left alone
SUBSERVANT_QUIET = 3600  # a marked 30-99 worktree: the foreman may reuse it with its warm build cache meanwhile
SUBSERVANTS_FROM = 30  # servants work only in worktrees 30-99 (the user, skills plan 0013)
LEAD = lead_marker.LEAD
ref_exists = lead_marker.ref_exists
unsaved_for_lead = lead_marker.unsaved_for_lead


def git(path: str, *args: str) -> str:
    return tick.git(path, *args)


def unsaved(path: str, slot: str, base: str) -> list[str]:
    """What the worktree holds that `base` (origin's default branch) lacks: commits on HEAD or a side branch, changes."""
    out = []
    ahead = git(path, "rev-list", "--count", f"{base}..HEAD")
    if ahead and ahead != "0":
        out.append(f"{ahead} commit(s) not on {base}")
    for ref in git(path, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{slot}-*").split():
        n = git(path, "rev-list", "--count", f"{base}..{ref}")
        if n and n != "0":
            out.append(f"side branch {ref}: {n} commit(s) not on {base}")
    if git(path, "status", "--porcelain"):
        out.append("uncommitted changes")
    plan = Path(path) / "plans/CURRENT_PLAN"
    if plan.exists() and plan.read_text().strip():
        out.append(f"plans/CURRENT_PLAN names {plan.read_text().strip()}")
    return out


def marker(path: str) -> dict | None:
    """lead_marker's plans/LEAD with `at`, its mtime: the foreman's `plan.py assign` rewrites it when it reuses the
    worktree. A malformed marker is {bad: True, error, text}: still marked, never pruned."""
    lead = lead_marker.marker(path)
    if lead is None:
        return None
    try:
        return {**lead, "at": (Path(path) / LEAD).stat().st_mtime}
    except OSError:
        return {**lead, "at": time.time()}


def build_running(path: str) -> bool:
    """cleanup.py's `busy`: a process whose command line names the worktree."""
    try:
        p = subprocess.run([sys.executable, str(CLEANUP), "busy", "--worktree", path], cwd=path,
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return True
    return p.returncode == 1


def sessions(agents: list[dict], path: str) -> list[dict]:
    here = Path(path).resolve()
    return [a for a in agents if a.get("checkout") and Path(a["checkout"]).resolve() == here
            and a.get("state") not in GONE]


def held(slot: str, ctx: dict) -> str | None:
    """A queue ticket, a boss pause or an open question to the user (the tollman's log and the farmer's)."""
    if slot in ctx.get("waiting", set()) | ctx.get("landing", set()):
        return "it has a merge queue ticket or the boss paused it"
    if slot in logstate.waiting_for_user(ctx.get("log", []) + ctx.get("farmer_log", [])):
        return "it waits for the user's answer"
    return None


def refusal(w: dict, ctx: dict, agents: list[dict], now_ms: float, build=build_running) -> str | None:
    """Why the worktree `w` (path, `slot`) may not be pruned now, None when it may."""
    slot, path = w["slot"], w["path"]
    lead = marker(path)
    if lead is not None:
        return subservant_refusal(w, lead, ctx, agents, now_ms, build)
    why = unsaved(path, slot, tick.default_ref(path))
    if why:
        return "; ".join(why)
    why = held(slot, ctx)
    if why:
        return why
    for a in sessions(agents, path):
        if a.get("state") in BUSY:
            return f"its agent {a.get('pane_id')} is {a['state']}"
        if int(slot) >= 10 and now_ms - (a.get("since") or 0) < QUIET * 1000:
            return f"its session {a.get('pane_id')} was active in the last {QUIET // 60} min"
    if build(path):
        return "a build or test runs in it"
    return None


def subservant_refusal(w: dict, lead: dict, ctx: dict, agents: list[dict], now_ms: float, build) -> str | None:
    """`refusal` for a worktree marked plans/LEAD: its work belongs in origin/<foreman>, never on main."""
    slot, path = w["slot"], w["path"]
    if lead.get("bad"):
        return lead["error"]
    if int(slot) < SUBSERVANTS_FROM:
        return f"a servant's worktree below {SUBSERVANTS_FROM} (foreman {lead['slot']}) is never pruned"
    base = f"origin/{lead['slot']}"
    if not ref_exists(path, base):
        return f"its foreman's branch {base} does not exist"
    why = unsaved_for_lead(path, slot, base)
    if why:
        return "; ".join(why)
    why = held(slot, ctx)
    if why:
        return why
    if now_ms - lead["at"] * 1000 < SUBSERVANT_QUIET * 1000:
        return f"its plans/LEAD was written in the last {SUBSERVANT_QUIET // 60} min"
    for a in sessions(agents, path):
        if a.get("state") in BUSY:
            return f"its agent {a.get('pane_id')} is {a['state']}"
        if now_ms - (a.get("since") or 0) < SUBSERVANT_QUIET * 1000:
            return f"its session {a.get('pane_id')} was active in the last {SUBSERVANT_QUIET // 60} min"
    if build(path):
        return "a build or test runs in it"
    return None


def slots(main: str) -> list[dict]:
    """The repository's numbered worktrees (path, `slot`, head)."""
    out = []
    for w in mtm_scan.worktrees(main):
        name = Path(w["path"]).name
        if NUMBERED.fullmatch(name):
            out.append({"path": w["path"], "slot": name, "head": git(w["path"], "rev-parse", "HEAD")})
    return sorted(out, key=lambda w: w["slot"])


def scan(main: str, ctx: dict, agents: list[dict], now_ms: float | None = None, build=build_running) -> list[dict]:
    now_ms = now_ms if now_ms is not None else time.time() * 1000
    return [{**w, "why": refusal(w, ctx, agents, now_ms, build)} for w in slots(main)]
