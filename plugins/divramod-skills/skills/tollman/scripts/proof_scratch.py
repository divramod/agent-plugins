#!/usr/bin/env python3
"""A car's proof on its hitched sha when its field moved on (hal2 plan 0490 step 23, D24): a foreman that hitched and
committed on rode no train, since proof.py waited for the field's checkout to be at the hitched head. Now the hitched
sha is proven in the farm's kept scratch worktree; the field's checkout is never changed.

  root     the scratch folder beside the proof cache (`<tollman state>/cache/scratch/`, a test's temp root), holding
           one kept worktree `proof` of the repository (every field's sha is reachable: one object store) and its
           lock `proof.lock`
  lock     a proof holds the lock (flock, not waited for): a second proof at the same time is `wait`, never blocks
  ready    the kept worktree when it is one (its `.git` file names an admin folder that exists), else a broken one
           (not a worktree, prunable) dropped and made again: `git worktree add --detach`, hooks off, ADD seconds,
           once per farm (a full checkout: minutes on a loaded Mac)
  move     `git checkout --detach --force <sha>` + `git clean -fdx`: only the files that differ are written (seconds);
           a failing move drops the scratch, the next proof makes it again
  drop     `git worktree remove --force --force`; when that fails, the folder is deleted and `git worktree prune`
           drops the stale entry. Only a path under the scratch root is ever removed, never another field
  prove    the scratch's verdict ({state, lines, checks, ...}, proof.prove's shape) with no uncommitted work; a scratch
           that cannot be had is `wait` with the reason, never red, never cached (proof.verdict keeps green and red)

Every git call goes through bounded.run with one try (its process group goes on a timeout). The scratch is never
removed after a proof. A field at its hitched head keeps the fast path (D9) and starts no scratch.
"""

import contextlib
import fcntl
import shutil
import subprocess
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path: bounded)
import bounded

NAME = "proof"
LOCK = "proof.lock"
ADD = 240  # seconds for the first checkout of the whole tree: 2:51 at a load of 135 (2026-10-30)
MOVE = 120  # a checkout to another sha writes only the files that differ
REMOVE = 120
GIT = bounded.run  # the scratch's git calls; a test fakes it
NO_HOOKS = ["-c", "core.hooksPath=/dev/null"]


class Unmade(Exception):
    """The scratch worktree could not be had: the reason."""


def git(cwd, *args: str, limit: int) -> tuple[int, str]:
    """A scratch git call: (exit, output); 124 on a timeout, 127 when git cannot start."""
    try:
        p = GIT(["git", *NO_HOOKS, *args], cwd=str(cwd), timeout=limit, retry=False)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {limit} s"
    except OSError as e:
        return 127, str(e)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def first(text: str, code: int) -> str:
    return next((ln for ln in text.splitlines() if ln.strip()), f"exit {code}")[:300]


def inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def drop(field: str, path: Path, root: Path) -> None:
    """The scratch worktree removed (see the module); never raises, never touches a path outside `root`."""
    if not inside(path, root) or path.resolve() == root.resolve():
        return
    code, _ = git(field, "worktree", "remove", "--force", "--force", str(path), limit=REMOVE)
    if code == 0 and not path.exists():
        return
    shutil.rmtree(path, ignore_errors=True)
    git(field, "worktree", "prune", limit=REMOVE)


def is_worktree(path: Path) -> bool:
    """A linked worktree whose admin folder still exists (not prunable)."""
    try:
        text = (path / ".git").read_text().strip()
    except OSError:
        return False
    return text.startswith("gitdir: ") and (path / text[len("gitdir: "):]).is_dir()


def ready(field: str, head: str, root: Path) -> Path:
    """The kept scratch worktree, made when it is missing or broken; raises Unmade with the reason."""
    path = root / NAME
    if is_worktree(path):
        return path
    if path.exists() or path.is_symlink():
        drop(field, path, root)
    code, text = git(field, "worktree", "add", "--detach", "--quiet", str(path), head, limit=ADD)
    if code != 0:
        drop(field, path, root)
        raise Unmade(f"git worktree add failed: {first(text, code)}")
    return path


def move(field: str, path: Path, head: str, root: Path) -> None:
    """The scratch at `head`, nothing untracked left; a failure drops it (made again next time) and raises Unmade."""
    for args, what in ((("checkout", "--detach", "--force", "--quiet", head), "checkout"), (("clean", "-fdxq"), "clean")):
        code, text = git(path, *args, limit=MOVE)
        if code != 0:
            drop(field, path, root)
            raise Unmade(f"git {what} failed: {first(text, code)}")


@contextlib.contextmanager
def locked(root: Path):
    """The scratch's lock, held for one proof; Unmade when another proof holds it."""
    try:
        root.mkdir(parents=True, exist_ok=True)
        lock = (root / LOCK).open("a")
    except OSError as e:
        raise Unmade(f"its folder cannot be made: {e}") from None
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Unmade("another proof is using it") from None
        yield


def prove(field: str, head: str, barn: str, root: Path, prove_at) -> dict:
    """`prove_at(checkout, head, barn)` run in the kept scratch at `head`; `wait` when it cannot be had."""
    try:
        with locked(root):
            path = ready(field, head, root)
            move(field, path, head, root)
            return prove_at(str(path), head, barn)
    except Unmade as e:
        return {"state": "wait", "lines": [f"no proof yet: the field moved on from its hitched head {head[:12]} and "
                                           f"the scratch worktree could not be had: {e}"], "checks": []}
