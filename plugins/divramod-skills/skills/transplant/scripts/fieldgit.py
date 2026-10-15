"""The transplant skill's git helpers and its two pushes (hal2 plan 0286, D25); stdlib only.

`push` is the only place this skill pushes: the target's branch, and, from the old field's own session, the old
field's branch on origin made the barn's too by a guarded lease push.
"""
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn


def die(message: str, code: int = 1) -> NoReturn:
    print(f"transplant.py: {message}", file=sys.stderr)
    sys.exit(code)


def need(tool: str) -> None:
    if not shutil.which(tool):
        die(f"{tool} is missing: run scripts/install-prerequisites.sh (needs hal2)", 2)


def git(path: Path, *args: str) -> subprocess.CompletedProcess:
    need("git")
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)


def out(path: Path, *args: str) -> str:
    r = git(path, *args)
    return r.stdout.strip() if r.returncode == 0 else ""


def fields(repo: Path) -> dict[str, Path]:
    """Every checkout of the repository by its folder name (`09`, `34`, the yard's own name)."""
    lines = out(repo, "worktree", "list", "--porcelain").splitlines()
    paths = [Path(line.split(" ", 1)[1]) for line in lines if line.startswith("worktree ")]
    return {p.name: p for p in paths}


def main_checkout(repo: Path) -> Path:
    first = out(repo, "worktree", "list", "--porcelain").splitlines()[:1]
    return Path(first[0].split(" ", 1)[1]) if first and first[0].startswith("worktree ") else repo


def own_field(cwd: Path) -> str:
    top = out(cwd, "rev-parse", "--show-toplevel")
    if not top:
        die(f"{cwd} is not inside a git repository")
    return Path(top).name


def remote_sha(path: Path, branch: str) -> str | None:
    r = git(path, "ls-remote", "origin", f"refs/heads/{branch}")
    return r.stdout.split()[0] if r.returncode == 0 and r.stdout.strip() else None


def ancestor(path: Path, older: str, newer: str) -> bool:
    return git(path, "merge-base", "--is-ancestor", older, newer).returncode == 0


def barn(path: Path) -> str | None:
    """origin's default branch as last fetched (`origin/main`)."""
    for ref in (out(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"), "origin/main", "origin/master"):
        if ref and git(path, "rev-parse", "--verify", "-q", ref).returncode == 0:
            return ref
    return None


def kept(frm: str, tip: str, why: str) -> dict:
    return {"old": "kept", "note": f"origin/{frm} still holds the old tip {tip[:7]}: {why}"}


def reset_old(source: Path | None, frm: str, to: str, own: str) -> dict:
    """Make origin's `<from>` the barn's too, when that loses nothing (D25). `old` says what happened."""
    if source is None:
        return {"old": "kept", "note": f"field {frm} is gone: origin/{frm} is left as it is"}
    tip = remote_sha(source, frm)
    if tip is None:
        return {"old": "absent", "note": f"origin has no {frm}: nothing to reset"}
    if own != frm:
        return kept(frm, tip, "only the old field's own session resets it; the farmer deletes it once the plan is in "
                    "the barn")
    if git(source, "fetch", "-q", "origin").returncode != 0:
        return kept(frm, tip, "git fetch origin failed")
    held, base = remote_sha(source, to), barn(source)
    if out(source, "branch", "--show-current") != frm or base is None or not ancestor(source, "HEAD", base):
        return kept(frm, tip, f"field {frm} is not on the barn")
    if held is None or not ancestor(source, tip, held):
        return kept(frm, tip, f"origin/{to} does not hold {tip[:7]} yet")
    if out(source, "rev-parse", "HEAD") == tip:
        return {"old": "same", "note": f"origin/{frm} is the barn's already"}
    plain = ancestor(source, tip, "HEAD")
    lease = [] if plain else [f"--force-with-lease={frm}:{tip}"]
    r = git(source, "push", *lease, "origin", f"HEAD:refs/heads/{frm}")
    if r.returncode != 0:
        return kept(frm, tip, f"the push was refused: {(r.stderr or r.stdout).strip()[-200:]}")
    return {"old": "plain" if plain else "lease", "note": f"origin/{frm} was {tip[:7]}, is now the barn's"}


def push(repo: Path, frm: str, to: str) -> dict:
    """`git push -u origin HEAD` in the target, then the old field's branch (only from the old field's session)."""
    where, own = fields(repo), own_field(repo)
    target = where.get(to)
    if target is None:
        die(f"field {to} does not exist")
    if git(target, "remote", "get-url", "origin").returncode != 0:
        return {"origin": False, "pushed": [], "old": "none", "note": "the farm has no origin: nothing pushed"}
    branch = out(target, "branch", "--show-current")
    if branch != to:
        die(f"field {to} is on branch '{branch}', not {to}: nothing pushed")
    r = git(target, "push", "-u", "origin", "HEAD")
    if r.returncode != 0:
        die(f"git push -u origin HEAD in field {to} failed: {(r.stderr or r.stdout).strip()}")
    return {"origin": True, "pushed": [to], **reset_old(where.get(frm), frm, to, own)}
