"""A repository's units, settings and git facts for fix-loc.

A unit is `code/<lang>/{apps,libs,scripts}/<name>` (hal2's layout, the repo-root-allowlist ADR), or a
folder matched by a `units` glob in `.hal/fix-loc.toml`; a file belongs to its most specific unit.
"""

import fnmatch
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_EXCLUDE = [
    "*/tests/*", "*/Tests/*", "*/__tests__/*", "*/tests.rs", "*/test.rs", "*_tests.rs",
    "*Tests.swift", "*/test_*.py", "*_test.*", "*.test.*", "*.spec.*",
    "*/fixtures/*", "*/generated/*", "*/Generated/*", "*.generated.*", "*/__snapshots__/*",
    "*/dist/*", "*/node_modules/*", "*/target/*", "*/.build/*", "*/vendor/*",
]
DEFAULT_UNITS = ["code/*/apps/*", "code/*/libs/*", "code/*/scripts/*"]


@dataclass
class Settings:
    limit: int = 300
    exclude: list = field(default_factory=list)
    units: list = field(default_factory=list)


def settings(root):
    """`.hal/fix-loc.toml` of `root` (limit, exclude, units); defaults when it is missing."""
    path = Path(root) / ".hal" / "fix-loc.toml"
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    return Settings(
        limit=int(data.get("limit", 300)),
        exclude=list(data.get("exclude", [])),
        units=list(data.get("units", [])),
    )


def excluded(path, extra=()):
    """Whether `path` is a test, generated, fixture or build file (or matches `extra`)."""
    anchored = "/" + path
    return any(fnmatch.fnmatchcase(anchored, pattern) for pattern in [*DEFAULT_EXCLUDE, *extra]) or any(
        fnmatch.fnmatchcase(path, pattern) for pattern in extra
    )


def unit_of(path, globs=()):
    """The most specific unit folder of `path`, or None when it belongs to none."""
    parts = Path(path).parts
    best = None
    for pattern in [*DEFAULT_UNITS, *globs]:
        depth = len(Path(pattern).parts)
        if len(parts) > depth and fnmatch.fnmatchcase("/".join(parts[:depth]), pattern):
            if best is None or depth > len(Path(best).parts):
                best = "/".join(parts[:depth])
    return best


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def tracked(root):
    """The files git tracks in `root`'s working tree."""
    return [line for line in git(root, "ls-files").splitlines() if line]


def default_branch(root):
    """`origin/<default>`: origin's HEAD, else origin/main."""
    try:
        return git(root, "rev-parse", "--abbrev-ref", "origin/HEAD").strip()
    except subprocess.CalledProcessError:
        return "origin/main"


def commits_per_file(root, ref, days=90):
    """{path: commits touching it in the last `days` days} on `ref`."""
    counts = {}
    out = git(root, "log", ref, f"--since={days}.days", "--name-only", "--format=")
    for line in out.splitlines():
        if line:
            counts[line] = counts.get(line, 0) + 1
    return counts


def busy_files(root, ref, skip_branches=()):
    """Files changed on other worktrees' unlanded branches or in their uncommitted work."""
    busy = set()
    worktree, branch = None, None
    for line in git(root, "worktree", "list", "--porcelain").splitlines() + [""]:
        if line.startswith("worktree "):
            worktree = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            branch = line.split("refs/heads/", 1)[-1]
        elif not line and worktree:
            if branch and branch not in skip_branches and f"origin/{branch}" != ref:
                busy.update(_changed(root, ref, branch, worktree))
            worktree, branch = None, None
    return busy


def _changed(root, ref, branch, worktree):
    try:
        names = git(root, "diff", "--name-only", f"{ref}...{branch}").splitlines()
        names += [line[3:] for line in git(worktree, "status", "--porcelain").splitlines()]
    except subprocess.CalledProcessError:
        return []
    return [name for name in names if name]
