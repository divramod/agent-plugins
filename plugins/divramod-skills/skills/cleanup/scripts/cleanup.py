#!/usr/bin/env python3
"""Find and delete the build artifacts of a git worktree, without asking.

Usage: cleanup.py <command> [options] [--worktree NAME|PATH]
  list [--json]            this worktree's git-ignored paths: `artifact` (delete takes it), `kept` or `unknown`,
                           with size and how it comes back
  busy                     processes whose command line names this worktree (a build still running); exit 1 if any
  delete [--dry-run] [PATH...]
                           delete PATHs (worktree-relative), or with none every `artifact`. Every path must be
                           git-ignored, hold no tracked file and not be protected.

What counts: the repo's `.hal/cleanup` (one glob per line relative to the worktree root, `*` within a folder,
`**` across folders; `!glob` keeps; a trailing `# ...` says how it comes back), or without that file generic
build folders (target/, build/, .build/, dist/, __pycache__/, ...; fetched dependencies like node_modules/ are
kept). Ignored paths no rule names are `unknown` and never deleted in bulk. Protected, never listed or deleted:
.git, .hal, .secrets, .env*, plans/, shotfiles/, *.machine.toml. Exit 2: git is missing.

--worktree works on another checkout of the current repository than the one it runs in: a worktree's folder name
or branch (`03`, `main`) as `git worktree list` shows it, or a path to any checkout.
"""
import fnmatch
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

LIST = ".hal/cleanup"
# Without .hal/cleanup: directory names that are artifacts (or kept dependencies) wherever they are ignored.
GENERIC = {
    "artifact": ["target", "build", ".build", "dist", "out", ".next", ".nuxt", ".turbo", ".parcel-cache",
                 ".svelte-kit", "coverage", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                 ".gradle", ".swiftpm", "DerivedData", ".cache", "*.egg-info", "*.xcresult", "*.noindex", ".tox"],
    "kept": ["node_modules", ".venv", "venv", "Pods", "Carthage", "vendor/bundle"],
}
PROTECTED = [".git", ".hal", ".hal/*", ".secrets", ".secrets/*", ".env", ".env.*", "plans", "plans/*",
             "shotfiles", "shotfiles/*", "*.machine.toml", "*/.env", "*/.env.*"]


def git(*args, check=True):
    if not shutil.which("git"):
        print("cleanup.py: git is missing; run install-prerequisites.sh", file=sys.stderr)
        sys.exit(2)
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check).stdout


TARGET = None  # --worktree: the checkout to clean instead of the current one


def worktree_named(name: str) -> Path:
    """The checkout of the current repository whose folder name or branch is name."""
    found = []
    for block in git("worktree", "list", "--porcelain").split("\n\n"):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines() if line)
        path, branch = fields.get("worktree"), fields.get("branch", "").removeprefix("refs/heads/")
        if path and name in (Path(path).name, branch):
            found.append(Path(path))
    if len(found) != 1:
        why = "no worktree" if not found else "several worktrees"
        print(f"cleanup.py: {why} named {name} in this repository", file=sys.stderr)
        sys.exit(1)
    return found[0]


def toplevel() -> Path:
    where = []
    if TARGET:
        target = Path(TARGET).expanduser()
        where = ["-C", str(target if target.is_dir() else worktree_named(TARGET))]
    try:
        return Path(git(*where, "rev-parse", "--show-toplevel").strip())
    except subprocess.CalledProcessError:
        print(f"cleanup.py: not inside a git worktree{' (' + TARGET + ')' if TARGET else ''}", file=sys.stderr)
        sys.exit(1)


def rules(top: Path):
    """The rules of `.hal/cleanup` as (glob, kind, how), in file order; None without the file."""
    path = top / LIST
    if not path.is_file():
        return None
    out = []
    for line in path.read_text().splitlines():
        glob, _, how = line.partition("#")
        glob = glob.strip()
        if not glob:
            continue
        kind = "kept" if glob.startswith("!") else "artifact"
        out.append((glob.lstrip("!").strip().strip("/"), kind, how.strip()))
    return out


def matches(glob: str, rel: str) -> bool:
    """Whether the worktree-relative path matches the glob: `*` within one folder, `**` any number of them."""
    def go(pat, parts):
        if not pat:
            return not parts
        if pat[0] == "**":
            return any(go(pat[1:], parts[i:]) for i in range(len(parts) + 1))
        return bool(parts) and fnmatch.fnmatchcase(parts[0], pat[0]) and go(pat[1:], parts[1:])
    return go(glob.split("/"), rel.split("/"))


def classify(rel: str, listed):
    """(kind, how) of an ignored path, by its own or an enclosing folder's rule; the last matching rule wins."""
    parts = rel.split("/")
    prefixes = ["/".join(parts[:i]) for i in range(len(parts), 0, -1)]
    if listed is not None:
        for prefix in prefixes:
            hits = [(kind, how) for glob, kind, how in listed if matches(glob, prefix)]
            if hits:
                return hits[-1]
        return "unknown", ""
    for prefix in prefixes:
        name = prefix.rsplit("/", 1)[-1]
        for kind, names in GENERIC.items():
            if any(fnmatch.fnmatch(name, n) or prefix.endswith("/" + n) or prefix == n for n in names):
                return kind, ""
    return "unknown", ""


def protected(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, p) for p in PROTECTED)


def size(path: Path) -> int:
    if path.is_symlink() or path.is_file():
        return path.lstat().st_size
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def human(n: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024


def ignored(top: Path):
    """Git-ignored untracked entries, collapsed to the outermost ignored directory."""
    out = git("-C", str(top), "ls-files", "--others", "--ignored", "--exclude-standard", "--directory")
    return sorted({line.rstrip("/") for line in out.splitlines() if line.strip()})


def artifacts(top: Path):
    listed = rules(top)
    entries = [e for e in ignored(top) if not protected(e)]
    kinds = {e: classify(e, listed) for e in entries}
    # git lists some ignored files and their untracked directory both: an unknown directory with listed content
    # gives way to that content, a known one covers it.
    keep = [e for e in entries
            if not (kinds[e][0] == "unknown" and any(o.startswith(e + "/") for o in entries))]
    keep = [e for e in keep if not any(e.startswith(o + "/") for o in keep)]
    rows = []
    for rel in keep:
        kind, how = kinds[rel]
        path = top / rel
        if not path.exists() and not path.is_symlink():
            continue
        rows.append({"path": rel, "kind": kind, "size": size(path), "rebuild": how, "selected": kind == "artifact"})
    return rows, listed is not None


def cmd_list(args):
    top = toplevel()
    rows, listed = artifacts(top)
    if "--json" in args:
        print(json.dumps({"worktree": str(top), "rules": LIST if listed else "generic", "artifacts": rows},
                         indent=2))
        return 0
    print(f"worktree {top} (rules: {LIST if listed else 'generic'})")
    for r in sorted(rows, key=lambda r: -r["size"]):
        mark = "*" if r["selected"] else " "
        print(f"{mark} {human(r['size']):>7}  {r['kind']:<8}  {r['path']}" + (f"  ({r['rebuild']})" if r["rebuild"] else ""))
    sel = sum(r["size"] for r in rows if r["selected"])
    print(f"selected (*): {human(sel)} of {human(sum(r['size'] for r in rows))}")
    return 0


def cmd_busy(_args):
    top = str(toplevel())
    out = subprocess.run(["ps", "-A", "-o", "pid=,command="], capture_output=True, text=True).stdout
    me = {os.getpid(), os.getppid()}
    hits = []
    for line in out.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if top + "/" in cmd + "/" and int(pid) not in me and "cleanup.py" not in cmd:
            hits.append(f"{pid}\t{cmd}")
    print("\n".join(hits) if hits else "idle")
    return 1 if hits else 0


def check(top: Path, rel: str):
    """Why rel must not be deleted, or None."""
    path = (top / rel).resolve() if not (top / rel).is_symlink() else (top / rel).parent.resolve() / (top / rel).name
    if top.resolve() not in path.parents:
        return "outside the worktree"
    rel = str(path.relative_to(top.resolve()))
    if protected(rel):
        return "protected"
    if not (top / rel).exists() and not (top / rel).is_symlink():
        return "does not exist"
    if git("-C", str(top), "ls-files", "--", rel).strip():
        return "holds tracked files"
    if subprocess.run(["git", "-C", str(top), "check-ignore", "-q", rel]).returncode != 0:
        return "not git-ignored"
    return None


def cmd_delete(args):
    top = toplevel()
    dry = "--dry-run" in args
    paths = [a for a in args if not a.startswith("--")]
    if not paths:
        paths = [r["path"] for r in artifacts(top)[0] if r["selected"]]
    status, freed = 0, 0
    for rel in paths:
        why = check(top, rel.rstrip("/"))
        if why:
            print(f"skip    {rel}: {why}")
            status = 1
            continue
        path = top / rel.rstrip("/")
        n = size(path)
        if not dry:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        freed += n
        print(f"{'would delete' if dry else 'deleted'} {human(n):>7}  {rel}")
    print(f"{'would free' if dry else 'freed'} {human(freed)}")
    return status


COMMANDS = {"list": cmd_list, "busy": cmd_busy, "delete": cmd_delete}

if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--worktree" in argv:
        i = argv.index("--worktree")
        if i + 1 >= len(argv):
            print("cleanup.py: --worktree needs a name or path", file=sys.stderr)
            sys.exit(1)
        TARGET = argv[i + 1]
        del argv[i:i + 2]
    if not argv or argv[0] not in COMMANDS:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)
    sys.exit(COMMANDS[argv[0]](argv[1:]))
