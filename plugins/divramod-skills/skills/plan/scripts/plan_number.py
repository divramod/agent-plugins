#!/usr/bin/env python3
"""Unique, increasing plan numbers across every worktree and branch of a repository.

A plan number is taken when any of these holds a `plans/<NNNN>-...` entry (a plan folder or an old flat file; the legacy
`docs/plans/` location still counts, so unmerged old branches can't cause duplicates):
the working tree of any worktree (main, user or feature worktrees, committed or not), any local branch, any
remote-tracking branch, or the reservation file in the git common directory, which all worktrees of a clone
share. `next` takes the highest taken number + 1 and reserves it under a file lock, so two worktrees creating a
plan at the same moment never get the same number. Gaps are fine; duplicates are not.

  plan_number.py next [--slug <slug>] [--fetch] [--no-reserve]   print the next number (and reserve it)
  plan_number.py list                                            print every taken number and where it was seen
  plan_number.py check                                           exit 1 when a number is used by two plans

Other numbered folders reuse it with their own folders and reservation file (the research skill:
`research/<NNNN>-<slug>/`, `research-numbers.json`): pass `dirs=` and `file=` to the functions, `kind=` to `main`.

Run inside the repository or pass --root. Other clones (other machines) are seen only through remote-tracking
branches: pass --fetch to update them first.
"""
import argparse
import datetime as dt
import fcntl
import json
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

PLAN_DIRS = ("plans", "docs/plans")  # docs/plans: legacy location, still counted
ENTRY_RE = re.compile(r"^(\d{4})-(.+?)(\.md)?$")
RESERVATIONS = "plan-numbers.json"


class NumberError(Exception):
    pass


def git(root: Path, *args: str, check: bool = True) -> str:
    if shutil.which("git") is None:
        print("plan_number.py: git is missing; run install-prerequisites.sh", file=sys.stderr)
        sys.exit(2)
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise NumberError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout if result.returncode == 0 else ""


def common_dir(root: Path) -> Path | None:
    out = git(root, "rev-parse", "--git-common-dir", check=False).strip()
    return (root / out).resolve() if out else None


def parse(name: str) -> tuple[int, str] | None:
    match = ENTRY_RE.match(name)
    return (int(match.group(1)), f"{match.group(1)}-{match.group(2)}") if match else None


def worktree_paths(root: Path) -> list[Path]:
    out = git(root, "worktree", "list", "--porcelain", check=False)
    paths = [Path(line[9:]) for line in out.splitlines() if line.startswith("worktree ")]
    return paths or [root]


def refs(root: Path) -> list[str]:
    out = git(root, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes", check=False)
    return [ref for ref in out.splitlines() if not ref.endswith("/HEAD")]


def taken(root: Path, dirs: tuple[str, ...] = PLAN_DIRS, file: str = RESERVATIONS) -> dict[int, dict[str, set[str]]]:
    """number -> {slug -> places it was seen}."""
    found: dict[int, dict[str, set[str]]] = {}

    def add(name: str, place: str) -> None:
        parsed = parse(name)
        if parsed:
            found.setdefault(parsed[0], {}).setdefault(parsed[1], set()).add(place)

    for tree in worktree_paths(root):
        for plans in dirs:
            folder = tree / plans
            if folder.is_dir():
                for entry in folder.iterdir():
                    add(entry.name, f"worktree {tree}")
    for ref in refs(root):
        for plans in dirs:
            for name in git(root, "ls-tree", "--name-only", f"{ref}:{plans}", check=False).splitlines():
                add(name, ref.removeprefix("refs/heads/").removeprefix("refs/"))
    for slug in reservations(root, file):
        add(slug, "reserved")
    return found


def reservations(root: Path, file: str = RESERVATIONS) -> dict[str, dict]:
    folder = common_dir(root)
    path = folder / file if folder else None
    if not path or not path.is_file():
        return {}
    return json.loads(path.read_text() or "{}")


@contextmanager
def locked(root: Path, file: str = RESERVATIONS):
    folder = common_dir(root)
    if folder is None:
        raise NumberError(f"not a git repository: {root}")
    with open(folder / (file + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield folder / file


def next_number(root: Path, slug: str = "", reserve: bool = True, dirs: tuple[str, ...] = PLAN_DIRS,
                file: str = RESERVATIONS) -> int:
    """Highest taken number + 1; with `reserve`, recorded for `slug` so no other worktree can take it."""
    if not reserve:
        return max(taken(root, dirs, file), default=0) + 1
    with locked(root, file) as path:
        booked = json.loads(path.read_text() or "{}") if path.is_file() else {}
        for existing, info in booked.items():
            if slug and existing.split("-", 1)[1] == slug:
                return info["number"]  # same plan asked twice: same number
        number = max(taken(root, dirs, file), default=0) + 1
        key = f"{number:04d}-{slug or 'reserved'}"
        booked[key] = {"number": number, "at": dt.datetime.now().isoformat(timespec="seconds"),
                       "worktree": str(root)}
        path.write_text(json.dumps(booked, indent=2, sort_keys=True) + "\n")
        return number


def duplicates(root: Path, dirs: tuple[str, ...] = PLAN_DIRS, file: str = RESERVATIONS) -> dict[int, dict[str, set[str]]]:
    """Numbers used by more than one plan; a reservation for a plan that exists under that number doesn't count."""
    clashes = {}
    for number, slugs in taken(root, dirs, file).items():
        real = {slug: places for slug, places in slugs.items() if places != {"reserved"}}
        reserved_only = [s for s, places in slugs.items() if places == {"reserved"}]
        if len(real) > 1 or (not real and len(reserved_only) > 1):
            clashes[number] = slugs
    return clashes


def places(seen: set[str], shown: int = 3) -> str:
    """`main, user, 00 +61 more`: where a plan was seen, main first, then shortest names."""
    names = sorted(seen, key=lambda n: (n != "main", len(n), n))
    extra = len(names) - shown
    return ", ".join(names[:shown]) + (f" +{extra} more" if extra > 0 else "")


def main(argv: list[str], kind: str = "plan", dirs: tuple[str, ...] = PLAN_DIRS, file: str = RESERVATIONS,
         doc: str | None = None) -> int:
    """The CLI; `kind` names what is numbered in messages (plan, research), `dirs` and `file` as in `taken`."""
    parser = argparse.ArgumentParser(description=doc or __doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    p_next = sub.add_parser("next")
    p_next.add_argument("--slug", default="")
    p_next.add_argument("--fetch", action="store_true", help="git fetch --all first, to see other clones")
    p_next.add_argument("--no-reserve", action="store_true")
    sub.add_parser("list")
    sub.add_parser("check")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        if args.command == "next":
            if args.fetch:
                git(root, "fetch", "--all", "--quiet")
            print(f"{next_number(root, args.slug, not args.no_reserve, dirs, file):04d}")
            return 0
        if args.command == "list":
            data = {f"{n:04d}": {s: sorted(p) for s, p in slugs.items()} for n, slugs in sorted(taken(root, dirs, file).items())}
            print(json.dumps(data, indent=2))
            return 0
        clashes = duplicates(root, dirs, file)
        for number, slugs in sorted(clashes.items()):
            print(f"{number:04d} is used by: " + "; ".join(f"{s} ({places(p)})" for s, p in slugs.items()))
        if not clashes:
            print(f"ok: no {kind} number is used twice")
        return 1 if clashes else 0
    except NumberError as error:
        print(f"{kind}_number.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
