#!/usr/bin/env python3
"""Unique, increasing research numbers across every worktree and branch of a repository.

A research number is taken when any of these holds a `research/<NNNN>-...` folder: the working tree of any worktree
(committed or not), any local branch, any remote-tracking branch, or the reservation file `research-numbers.json`
in the git common directory, which all worktrees of a clone share. `next` takes the highest taken number + 1 and
reserves it under a file lock. Gaps are fine; duplicates are not. The logic is the plan skill's plan_number.py,
reused with research's folder and reservation file.

  research_number.py next [--slug <slug>] [--fetch] [--no-reserve]   print the next number (and reserve it)
  research_number.py list                                            every taken number and where it was seen
  research_number.py check                                           exit 1 when a number is used by two docs

Run inside the repository or pass --root. Other clones are seen only through remote-tracking branches: --fetch.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plan" / "scripts"))
import plan_number  # noqa: E402  (the plan skill's numbering, shared)

DIRS = ("research",)
RESERVATIONS = "research-numbers.json"
NumberError = plan_number.NumberError


def taken(root: Path) -> dict[int, dict[str, set[str]]]:
    return plan_number.taken(root, DIRS, RESERVATIONS)


def next_number(root: Path, slug: str = "", reserve: bool = True) -> int:
    return plan_number.next_number(root, slug, reserve, DIRS, RESERVATIONS)


def duplicates(root: Path) -> dict[int, dict[str, set[str]]]:
    return plan_number.duplicates(root, DIRS, RESERVATIONS)


def main(argv: list[str]) -> int:
    return plan_number.main(argv, kind="research", dirs=DIRS, file=RESERVATIONS, doc=__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
