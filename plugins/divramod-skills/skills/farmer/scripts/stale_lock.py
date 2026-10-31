"""A stale `index.lock` in a role's worktree, removed before the round's merge from main (hal2 plan 0490 step 11,
L52 and L69 of the tollman: mfm-failed woke it for a lock no process held, twice).

The lock is the worktree's own (`<git dir>/index.lock`, the git dir read from the worktree's `.git` file, no
process). It goes only when it is older than AGE, no process has it open (`lsof -t <lock>`) and no git process works
in the worktree (`pgrep -x git`, their cwd by `lsof -d cwd`); `lsof` missing or failing keeps it. A round without a
lock costs one stat.
"""

import subprocess
import time
from pathlib import Path

AGE = 10 * 60


def git_dir(top: str) -> Path:
    """The worktree's git dir: `.git` itself, or the folder its `gitdir:` line names."""
    dot = Path(top) / ".git"
    if dot.is_file():
        line = dot.read_text().strip()
        if line.startswith("gitdir:"):
            path = Path(line[7:].strip())
            return path if path.is_absolute() else (Path(top) / path).resolve()
    return dot


def out(argv: list[str]) -> str | None:
    """A command's stdout, None when it cannot run; lsof and pgrep exit 1 when they find nothing ("")."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode in (0, 1) else None


def busy(lock: Path, top: str, sh=out) -> bool:
    """A process holds the lock or a git process works in the worktree (unknown counts as busy)."""
    holders = sh(["lsof", "-t", str(lock)])
    if holders is None or holders.strip():
        return True
    gits = sh(["pgrep", "-x", "git"])
    if gits is None:
        return True
    pids = ",".join(gits.split())
    if not pids:
        return False
    cwds = sh(["lsof", "-a", "-d", "cwd", "-Fn", "-p", pids])
    if cwds is None:
        return True
    here = str(Path(top).resolve())
    return any(ln[1:] == here or ln[1:].startswith(here + "/") for ln in cwds.splitlines() if ln.startswith("n"))


def clear(top: str, now: float | None = None, sh=out) -> str | None:
    """Remove a stale index.lock of the worktree `top`; the line to log when it did, else None."""
    lock = git_dir(top) / "index.lock"
    try:
        age = (now or time.time()) - lock.stat().st_mtime
    except OSError:
        return None
    if age < AGE or busy(lock, top, sh):
        return None
    try:
        lock.unlink()
    except OSError:
        return None
    return f"removed a stale {lock} ({int(age // 60)} min old, no process held it, no git in the worktree; L52, L69)"
