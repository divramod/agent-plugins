"""Prune's hands (hal2 plan 0377 step 5; first the tollman's prune_act.py, copied by step 3, D11): the run's actions on
one field of step 3's facts (`{slot, path, sessions, ...}`), each called by executor.py only after the proof ran again
(PR21), one at a time (D14). Every command runs without a timeout (D7): a removal killed mid-delete left 5435 tracked
files deleted; the executor journals a removal (halfway.py) so a killed one is resumed.

- `remove`: the field's resting sessions stopped by signal (delete-field's stop.py through `hal2-cli-agents stop`,
  never a typed `/exit`), its kept fix worktree `<NN>-fix` removed (`git worktree remove`, never forced: the proof
  checked it, prune_proof.fix_unsaved), then `hal2-cli-git worktree remove NN --remote`; a servant's `--force`, then
  origin/NN deleted once it is in origin/<foreman> (hal2's `--remote` only deletes a branch origin's default branch
  contains).
- `clean`: muck out (the cleanup skill's own set) or trim (the config's paths): `cleanup.py busy` (a build running
  skips it), then `cleanup.py delete --worktree <path> [<path in the field>...]`; a trim (only while the disk is
  short) also mucks out the field's `<NN>-fix` (hal2 plan 0604 D11), a muck out of the field leaves it warm.

A hand returns (status, text): status `success`, `failure` or `skipped` (the workflow command's end of a step).
"""

import json
import subprocess
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
from prune_proof import CLEANUP, fix_of, git, ref_exists
from skillpath import sibling

STOP = sibling("delete-field") / "scripts/stop.py"
EXIT_WAIT = 15


def run(argv: list[str], cwd: str) -> tuple[int, str]:
    """`argv`'s exit code and output, never under a timeout (D7); 127 when it cannot start."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    except OSError as e:
        return 127, str(e)
    return p.returncode, (p.stdout + p.stderr).strip()


def status(code: int) -> str:
    return "success" if code == 0 else "failure"


def stop(main: str, pane: str) -> str | None:
    """delete-field's stop.py on `pane`: by signal (hal2-cli-agents stop), never a typed `/exit`, which
    was not taken (hal2 plan 0212, 2026-10-08); None when it is gone, else why not (a draft, background tasks)."""
    code, text = run([sys.executable, str(STOP), "stop", pane, "--repo", main, "--wait", str(EXIT_WAIT)], main)
    if code == 0:
        return None
    if code == 3:
        try:
            return json.loads(text or "{}").get("refused") or "refused"
        except ValueError:
            return "refused"
    return f"did not stop: {text[-300:]}"


def end_sessions(main: str, panes: list[str]) -> str | None:
    """Every resting session stopped by signal; the first that refuses (a draft, background tasks) stops the action."""
    for pane in panes:
        refused = stop(main, pane)
        if refused:
            return f"{pane}: not stopped: {refused}"
    return None


def remove(main: str, field: dict, foreman: str | None, panes: list[str]) -> tuple[str, str]:
    """The field removed, its sessions `panes` stopped first (a refusal skips the removal)."""
    problem = end_sessions(main, panes)
    if problem:
        return "skipped", problem
    fix = fix_of(field["path"], field["slot"])
    if fix:  # the field's kept fix worktree goes first, never forced (the proof checked it)
        code, text = run(["git", "worktree", "remove", fix], main)
        if code:
            return "skipped", f"its fix worktree {Path(fix).name} not removed: {text[-300:]}"
    state, text = remove_cmd(main, field["slot"], foreman)
    return state, (f"removed its fix worktree {Path(fix).name}\n" if fix else "") + text


def remove_cmd(main: str, slot: str, foreman: str | None, force: bool = False) -> tuple[str, str]:
    """`hal2-cli-git worktree remove`: `--remote` for a field of the default branch (`--force` too when a killed removal
    is resumed: its deleted files are its only change), a servant's by `remove_subservant`."""
    if foreman:
        return remove_subservant(main, slot, foreman)
    code, text = run(["hal2-cli-git", "worktree", "remove", slot, "--remote", *(["--force"] if force else [])], main)
    return status(code), text


def remove_subservant(main: str, slot: str, foreman: str) -> tuple[str, str]:
    """A free servant's worktree: `--force` (its branch is not on main by design), then origin/NN deleted once it is
    in origin/<foreman>."""
    remote = ref_exists(main, f"origin/{slot}")
    code, text = run(["hal2-cli-git", "worktree", "remove", slot, "--force"], main)
    if code or not remote:
        return status(code), text
    return drop_remote(main, slot, f"origin/{foreman}", text)


def drop_remote(main: str, slot: str, base: str, text: str = "") -> tuple[str, str]:
    """origin/NN deleted when `base` holds all of it, else kept and a failure (the proof should have refused)."""
    if git(main, "rev-list", "--count", f"{base}..origin/{slot}") != "0":
        return "failure", f"{text}\norigin/{slot} kept: it holds commits not in {base}".strip()
    code, out = run(["git", "push", "--quiet", "origin", "--delete", slot], main)
    return status(code), "\n".join(x for x in (text, out or f"deleted origin/{slot}") if x)


def cleanup(path: str, *args: str) -> tuple[int, str]:
    return run([sys.executable, str(CLEANUP), *args, "--worktree", path], path)


def clean(field: dict, paths: list[str] | None) -> tuple[str, str]:
    """Muck out (`paths` None: the cleanup skill's own set) or trim `paths`, after cleanup's `busy`; a listed path that
    is not there is nothing to do (cleanup.py would call it an error)."""
    path = field["path"]
    code, text = cleanup(path, "busy")
    if code == 1:
        return "skipped", f"a build or test runs in it: {text.splitlines()[0] if text else ''}"
    todo = None if paths is None else [p for p in paths if (Path(path) / p).exists() or (Path(path) / p).is_symlink()]
    fix = fix_of(path, field["slot"]) if paths is not None and field.get("slot") else None
    if todo == [] and not fix:
        return "success", f"nothing to trim: {', '.join(paths or [])} not there"
    code, text = cleanup(path, "delete", *(todo or [])) if todo != [] else (0, f"nothing to trim in {field['slot']}")
    if fix and cleanup(fix, "busy")[0] != 1:  # a trim mucks out the fix worktree too (the disk is short)
        more, out = cleanup(fix, "delete")
        code, text = code or more, f"{text}\n{Path(fix).name}: {out}".strip()
    return status(code), text
