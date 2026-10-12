"""A parallel plan's subservant slot (skills plan 0013), as every farmer duty reads it.

A slot whose worktree holds `plans/LEAD` (one line `<lead-slot> <plan> <step>`) runs one step of its lead's plan,
never lands and is measured against its lead's branch `origin/<lead-slot>`, never main. A malformed marker still
marks the slot (bad but marked: no landing, no restart by rule, the report names the broken marker); only a slot
without the file is unmarked. Used by mtm_scan, boss, lead_scan, trains, duties and prune.
"""

import re
import subprocess
from pathlib import Path

LEAD = Path("plans/LEAD")
NUMBERED = re.compile(r"\d\d")
IGNORED = (":!plans/LEAD", ":!plans/CURRENT_PLAN")  # a marked slot's runtime files, ignored or not


def git(path: str | Path, *args: str) -> str:
    """git's stdout, "" on failure."""
    try:
        p = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout.rstrip("\n") if p.returncode == 0 else ""


def ok(path: str | Path, *args: str) -> bool:
    try:
        return subprocess.run(["git", *args], cwd=path, capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def marker(path: str | Path) -> dict | None:
    """plans/LEAD as {slot, plan, step}; a malformed one as {bad: True, error, text}; None without the file."""
    f = Path(path) / LEAD
    if not f.is_file():
        return None
    try:
        text = f.read_text().strip()
    except OSError as e:
        text = f"<unreadable: {e}>"
    parts = text.split()
    if len(parts) < 3 or not NUMBERED.fullmatch(parts[0]):
        return {"bad": True, "text": text, "error": f"plans/LEAD is not `<lead-slot> <plan> <step>`: '{text}'"}
    return {"slot": parts[0], "plan": parts[1], "step": parts[2]}


def describe(lead: dict) -> str:
    if lead.get("bad"):
        return f"subservant with a broken marker ({lead['error']})"
    return f"subservant of slot {lead['slot']} (plan {lead['plan']} step {lead['step']})"


def ref_exists(path: str | Path, ref: str) -> bool:
    return bool(git(path, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"))


def unsaved_for_lead(path: str | Path, slot: str, lead: str) -> list[str]:
    """What a subservant's slot holds that `lead` (origin/<lead-slot>) lacks: commits on HEAD, origin/NN or a side
    branch, changes (plans/LEAD and plans/CURRENT_PLAN aside: they mark the slot, they are not work)."""
    out = []
    for ref in ["HEAD", *([f"origin/{slot}"] if ref_exists(path, f"origin/{slot}") else []),
                *git(path, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{slot}-*").split()]:
        n = git(path, "rev-list", "--count", f"{lead}..{ref}")
        if n != "0":
            out.append(f"{ref}: {n or 'some'} commit(s) not in {lead}")
    if git(path, "status", "--porcelain", "--untracked-files=all", "--", ".", *IGNORED):
        out.append("uncommitted changes")
    return out


def missing(path: str | Path, slot: str, lead: dict, default: str) -> list[str]:
    """What the marked slot holds that its lead's branch lacks; [] when all its work is there. A broken marker
    names no lead: measured against `default` (origin's default branch), the marker's error first."""
    if lead.get("bad"):
        why = unsaved_for_lead(path, slot, default)
        return [lead["error"], *why] if why else []
    base = f"origin/{lead['slot']}"
    if not ref_exists(path, base):
        return [f"its lead's branch {base} does not exist"]
    return unsaved_for_lead(path, slot, base)


def report_path(lead: dict) -> str:
    """The step's report as the removed `plan.py report` wrote it (skills plan 0013). Since skills plan 0016 nothing
    writes one: a stale plans/LEAD means the lead takes the work over, or plans/LEAD is deleted."""
    return f"plans/{lead['plan']}/reports/{lead['step']}.md"


def step_done(path: str | Path, slot: str, lead: dict) -> bool:
    """The subservant has finished its step: the step's report is on origin/NN, or its HEAD is in origin/<lead>
    with that report (the lead merged it; origin/NN may be gone). A fresh slot's HEAD is in origin/<lead> too, but
    holds no report of its step yet, so it is not done. A broken marker is never done."""
    if lead.get("bad"):
        return False
    report = report_path(lead)
    if ok(path, "cat-file", "-e", f"origin/{slot}:{report}"):
        return True
    return ok(path, "merge-base", "--is-ancestor", "HEAD", f"origin/{lead['slot']}") \
        and ok(path, "cat-file", "-e", f"HEAD:{report}")
