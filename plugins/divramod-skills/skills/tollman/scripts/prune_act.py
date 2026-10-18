"""The prune duty's hands (`prune.py clean|remove`, plan 0360 step 7): each checks the field again with
prune_proof.py, then cleans a field 00-09 (the cleanup skill's `delete`) or stops a field 10-99's resting session by
signal (delete-field's stop.py through `hal2-cli-agents stop`, never a typed `/exit`) and removes it
(`hal2-cli-git worktree remove NN --remote`; a servant's: `--force`, then origin/NN once in origin/<foreman>).
"""

import datetime as dt
import json
import subprocess
import sys
import time

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import logstate
import roles
import tick
from prune_proof import CLEANUP, git, marker, ref_exists, refusal, sessions, slots
from skillpath import sibling

STOP = sibling("delete-field") / "scripts/stop.py"
EXIT_WAIT = 15


def live(main: str) -> tuple[dict, list[dict]]:
    """The tollman's round context (queue, pauses, its log, the farmer's log for open questions) and the agents."""
    import tollman  # its wiring; tollman.py imports this module's caller (prune.py)
    ctx = tick.context(main, main, {}, dt.datetime.now(), True, tollman.WIRING)
    ctx["farmer_log"] = logstate.read_log(main, roles.ROLE)
    return ctx, list(ctx["agents_by_pane"].values())


def stop(main: str, pane: str) -> str | None:
    """delete-field's stop.py on `pane`: by signal (hal2-cli-agents stop), never a typed `/exit`, which
    was not taken (hal2 plan 0212, 2026-10-08); None when it is gone, else why not (a draft, background tasks)."""
    p = subprocess.run([sys.executable, str(STOP), "stop", pane, "--repo", main, "--wait", str(EXIT_WAIT)],
                       capture_output=True, text=True)
    if p.returncode == 0:
        return None
    if p.returncode == 3:
        return json.loads(p.stdout or "{}").get("refused") or "refused"
    return f"did not stop: {(p.stdout + p.stderr).strip()[-300:]}"


def end_sessions(main: str, path: str, slot: str, dry: bool) -> str | None:
    """End every resting session in the worktree by signal; a draft or running background tasks leave it running."""
    for a in sessions(live(main)[1], path):
        pane = a["pane_id"]
        if dry:
            print(f"would stop {pane} in {slot}")
            continue
        refused = stop(main, pane)
        if refused:
            return f"{pane}: not stopped: {refused}"
    return None


def act_on(main: str, slot: str, what: str, dry: bool) -> tuple[int, str]:
    w = next((x for x in slots(main) if x["slot"] == slot), None)
    if w is None:
        return 1, f"no numbered worktree {slot} in {main}"
    if (what == "clean") != (int(slot) < 10):
        return 1, f"{what} is for worktrees {'00-09' if what == 'clean' else '10-99'}"
    lead = marker(w["path"])
    if lead and not lead.get("bad") and what == "remove" and not dry:
        tick.git(main, "fetch", "--quiet", "--prune", "origin")  # checked again against the foreman's newest branch
    ctx, agents = live(main)
    why = refusal(w, ctx, agents, time.time() * 1000)
    if why:
        return 0, f"skipped {what} {slot}: {why}"
    if what == "clean":
        argv = [sys.executable, str(CLEANUP), "delete", "--worktree", w["path"]] + (["--dry-run"] if dry else [])
        p = subprocess.run(argv, cwd=w["path"], capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr).strip()
    problem = end_sessions(main, w["path"], slot, dry)
    if problem:
        return 0, f"skipped remove {slot}: {problem}"
    if lead:
        return remove_subservant(main, w, lead["slot"], dry)
    argv = ["hal2-cli-git", "worktree", "remove", slot, "--remote"]
    if dry:
        return 0, "would run " + " ".join(argv)
    return tick.sh(argv, main)


def remove_subservant(main: str, w: dict, lead_slot: str, dry: bool) -> tuple[int, str]:
    """A free servant's worktree: `--force` (its branch is not on main by design), then origin/NN deleted once it is
    in origin/<foreman> (hal2's `--remote` only deletes a branch origin's default branch contains)."""
    slot, base = w["slot"], f"origin/{lead_slot}"
    remote = ref_exists(main, f"origin/{slot}")
    argv = ["hal2-cli-git", "worktree", "remove", slot, "--force"]
    push = ["git", "push", "--quiet", "origin", "--delete", slot]
    if dry:
        return 0, "would run " + " ".join(argv) + ("; then " + " ".join(push) if remote else "")
    code, text = tick.sh(argv, main)
    if code or not remote:
        return code, text
    if git(main, "rev-list", "--count", f"{base}..origin/{slot}") != "0":
        return 1, f"{text}\norigin/{slot} kept: it holds commits not in {base}"
    pushed, out = tick.sh(push, main)
    return pushed, "\n".join(x for x in (text, out or f"deleted origin/{slot}") if x)
