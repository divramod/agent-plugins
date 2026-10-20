"""A parallel plan's servant worktree (skills plan 0013), as every farmer duty reads it.

A worktree that holds `plans/LEAD` (one line `<foreman-worktree> <plan> <step>`) runs one step of its foreman's plan,
never lands and is measured against its foreman's branch `origin/<foreman-worktree>`, never main. A malformed marker still
marks the worktree (bad but marked: no landing, no restart by rule, the report names the broken marker); only a worktree
without the file is unmarked. A marker is "stale" only by `state` (its foreman's plan done or gone, or its field
without session and unmerged work); a running servant's is in use. Used by mtm_scan, boss, lead_scan, trains, duties and prune.
"""

import re
import subprocess
from pathlib import Path

IN_USE, STALE, UNKNOWN = "in-use", "stale", "unknown"
GONE = {"ended", "failed"}  # an agent state that is no session any more

LEAD = Path("plans/LEAD")
NUMBERED = re.compile(r"\d\d")
IGNORED = (":!plans/LEAD", ":!plans/CURRENT_PLAN")  # a marked worktree's runtime files, ignored or not


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
        return {"bad": True, "text": text, "error": f"plans/LEAD is not `<foreman-worktree> <plan> <step>`: '{text}'"}
    return {"slot": parts[0], "plan": parts[1], "step": parts[2]}


def describe(lead: dict) -> str:
    """What the marker is: a servant of the foreman's plan (a running one is in use, never "stale": see state)."""
    if lead.get("bad"):
        return f"servant with a broken marker ({lead['error']})"
    return f"servant of field {lead['slot']}'s plan {lead['plan']} (step {lead['step']})"


def ref_exists(path: str | Path, ref: str) -> bool:
    return bool(git(path, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"))


def unsaved_for_lead(path: str | Path, slot: str, lead: str) -> list[str]:
    """What a servant's worktree holds that `lead` (origin/<foreman-worktree>) lacks: commits on HEAD, origin/NN or a side
    branch, changes (plans/LEAD and plans/CURRENT_PLAN aside: they mark the worktree, they are not work)."""
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
    """What the marked worktree holds that its foreman's branch lacks; [] when all its work is there. A broken marker
    names no foreman: measured against `default` (origin's default branch), the marker's error first."""
    if lead.get("bad"):
        why = unsaved_for_lead(path, slot, default)
        return [lead["error"], *why] if why else []
    base = f"origin/{lead['slot']}"
    if not ref_exists(path, base):
        return [f"its foreman's branch {base} does not exist"]
    return unsaved_for_lead(path, slot, base)


def report_path(lead: dict) -> str:
    """The step's report as the removed `plan.py report` wrote it (skills plan 0013). Since skills plan 0016 nothing
    writes one: a servant's step is done when its work is in the foreman's branch (see `missing`)."""
    return f"plans/{lead['plan']}/reports/{lead['step']}.md"


def step_done(path: str | Path, slot: str, lead: dict) -> bool:
    """The servant has finished its step: the step's report is on origin/NN, or its HEAD is in origin/<foreman>
    with that report (the foreman merged it; origin/NN may be gone). A fresh worktree's HEAD is in origin/<foreman> too, but
    holds no report of its step yet, so it is not done. A broken marker is never done."""
    if lead.get("bad"):
        return False
    report = report_path(lead)
    if ok(path, "cat-file", "-e", f"origin/{slot}:{report}"):
        return True
    return ok(path, "merge-base", "--is-ancestor", "HEAD", f"origin/{lead['slot']}") \
        and ok(path, "cat-file", "-e", f"HEAD:{report}")


# --- Is the marker in use? A servant of a running masterplan holds one (the user allowed it, plan 0294 D25).

def read(path: str | Path, *args: str) -> str | None:
    """git's stdout, None when git fails (unlike `git`, an empty answer and an unreadable one differ)."""
    try:
        p = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.rstrip("\n") if p.returncode == 0 else None


def default_ref(path: str | Path) -> str:
    """origin's default branch as `origin/<name>`, `origin/main` when it cannot be read."""
    return git(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") or "origin/main"


def statuses(text: str) -> list[str] | None:
    """The Status cells of a plan.md's step table (header with the columns Step and Status); None without one."""
    rows, col = [], None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            if col is not None:
                break
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if col is None:
            low = [c.lower() for c in cells]
            if "step" in low and "status" in low:
                col = low.index("status")
        elif not all(set(c) <= set("-: ") for c in cells) and col < len(cells):
            rows.append(cells[col])
    return rows or None


def foreman_over(foreman: Path, lead: dict) -> tuple[bool | None, str]:
    """(a) The foreman's plan is done or gone: True; open: False; None when the foreman's field or its plan.md cannot
    be read (a missing field is unknown, never "gone")."""
    slot, plan = lead["slot"], lead["plan"]
    if not (foreman / ".git").exists():
        return None, f"field {slot} is not readable"
    folder, flat = foreman / "plans" / plan / "plan.md", foreman / "plans" / f"{plan}.md"
    f = folder if folder.is_file() else flat
    if not f.is_file():
        return True, f"plan {plan} is gone from field {slot}"
    try:
        cells = statuses(f.read_text())
    except OSError:
        cells = None
    if cells is None:
        return None, f"the step table of plan {plan} in field {slot} cannot be read"
    if all(c.lower().lstrip("*_ ").startswith(("done", "dropped")) for c in cells):  # a dropped row is no open work
        return True, f"plan {plan} of field {slot} is done"
    return False, f"plan {plan} of field {slot} is open"


def unmerged(path: str | Path, slot: str, default: str) -> tuple[bool | None, list[str]]:
    """What the field holds that the default branch lacks (commits on HEAD or a side branch NN-*, uncommitted changes;
    plans/LEAD and plans/CURRENT_PLAN aside): (True, what), (False, []), or (None, []) when it cannot be read."""
    if read(path, "rev-parse", "--verify", "--quiet", f"{default}^{{commit}}") in (None, ""):
        return None, []
    out, unread = [], False
    refs = (read(path, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{slot}-*") or "").split()
    for ref in ["HEAD", *refs]:
        n = read(path, "rev-list", "--count", f"{default}..{ref}")
        unread |= n is None
        if n not in (None, "0"):
            out.append(f"{ref}: {n} commit(s) not on {default}")
    changes = read(path, "status", "--porcelain", "--untracked-files=all", "--", ".", *IGNORED)
    unread |= changes is None
    if changes:
        out.append("uncommitted changes")
    return (True, out) if out else (None if unread else False, [])


def session_in(path: str | Path, agents: list[dict] | None) -> bool | None:
    """An agent session runs in the field (from `hal2-cli-agents list --json`); None without a list."""
    if agents is None:
        return None
    here = Path(path).resolve()
    return any(a.get("checkout") and Path(a["checkout"]).resolve() == here and a.get("state") not in GONE
               for a in agents)


def state(path: str | Path, lead: dict, agents: list[dict] | None, default: str,
          foreman: str | Path | None = None) -> dict:
    """Is the marker of the field `path` in use? {state, reason}. The rule (plan 0294 D25), per fact true, false or
    unreadable: it is stale only when (a) the foreman it names has no plan any more or that plan is done, or (b) its
    own field has no agent session and no unmerged work. Both false: a servant's marker in use. Otherwise, and
    whenever a fact cannot be read (the foreman's field missing, no session list), unknown, never stale. A broken
    marker names no foreman: unknown."""
    if lead.get("bad"):
        return {"state": UNKNOWN, "reason": "the marker is broken, it names no foreman"}
    a, a_why = foreman_over(Path(foreman) if foreman else Path(path).resolve().parent / lead["slot"], lead)
    if a:
        return {"state": STALE, "reason": a_why}
    slot = Path(path).resolve().name
    session, (work, what) = session_in(path, agents), unmerged(path, slot, default)
    if session is False and work is False:
        return {"state": STALE, "reason": "its field has no agent session and no unmerged work"}
    if a is False and (session or work):
        return {"state": IN_USE, "reason": f"{a_why}; " + (
            "an agent session runs in the field" if session else "the field holds " + "; ".join(what))}
    unread = [w for w, x in ((a_why, a), ("the agent list is missing", session), (f"{default} or git cannot be read", work))
              if x is None]
    return {"state": UNKNOWN, "reason": "cannot tell: " + "; ".join(unread)}


def say(lead: dict, st: dict) -> str:
    """The marker in words, by its state: in use as a servant, never "stale"; stale with its reason."""
    what = describe(lead)
    if st["state"] == STALE:
        return f"stale plans/LEAD of {what}: {st['reason']}"
    if st["state"] == IN_USE:
        return f"{what}, in use ({st['reason']})"
    return f"{what}, whether it is in use is unknown ({st['reason']})"
