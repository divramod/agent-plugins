#!/usr/bin/env python3
"""The merge train's test: a trial merge (hal2's .adr/merge-queue-policy.md rule 3, hal2 plan 0169 step 11).

`ride` merges the carrier's branch into the default branch and then every waiter's branch into the result, in queue
order, with `git merge-tree --write-tree`: nothing is checked out and no ref moves (the trial commits dangle until
git's gc). A waiter whose merge is clean, or conflicts only in append-only docs and generated files (SOFT: the
carrier keeps both sides or regenerates), rides; one that conflicts anywhere else is left out with its files, and
the trial goes on without it.
"""

import subprocess

SOFT_NAMES = {"INTENT.md", "AGENTS.md", "CLAUDE.md", "Cargo.lock"}
SOFT_PARTS = ("hal2-workspace-hack/",)


def soft(path: str) -> bool:
    """A file whose conflict never keeps a branch off a train: append-only docs, lock files, the workspace-hack."""
    return path.rsplit("/", 1)[-1] in SOFT_NAMES or any(p in path for p in SOFT_PARTS)


def git(repo: str, *args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout.strip()


def merge(repo: str, ours: str, theirs: str) -> tuple[str | None, list[str]]:
    """The commit of `theirs` merged into `ours` and the files that conflict; (None, []) when git cannot say."""
    code, out = git(repo, "merge-tree", "--write-tree", "--name-only", "--no-messages", ours, theirs)
    lines = out.split("\n") if out else []
    if code not in (0, 1) or not lines:
        return None, []
    made, commit = git(repo, "-c", "user.name=farmer", "-c", "user.email=farmer@localhost", "commit-tree", lines[0],
                       "-p", ours, "-p", theirs, "-m", "merge train trial")
    return (commit if made == 0 else None), [f for f in lines[1:] if f]


def ride(repo: str, base: str, carrier: str, waiters: list[tuple[str, str]]) -> tuple[list[str], dict[str, list[str]]]:
    """`waiters` are (slot, branch) in queue order: the slots that ride and, per slot left out, why (its files that
    conflict outside SOFT, or `?` when the trial could not run)."""
    acc, _ = merge(repo, base, carrier)
    acc = acc or carrier
    riders, left = [], {}
    for slot, branch in waiters:
        commit, files = merge(repo, acc, branch)
        hard = [f for f in files if not soft(f)]
        if commit is None or hard:
            left[slot] = hard or ["?"]
            continue
        riders.append(slot)
        acc = commit
    return riders, left
