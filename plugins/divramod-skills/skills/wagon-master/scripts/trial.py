#!/usr/bin/env python3
"""The wagon train's test: a trial merge (hal2's .adr/merge-queue-policy.md rule 3, hal2 plan 0169 step 11; the
train engine's since hal2 plan 0294 step 6).

`merge` merges one head into another with `git merge-tree --write-tree`: nothing is checked out and no ref moves
(the trial commit dangles until git's gc). `trains.draft` chains them in queue order onto the barn's head with what
the wagon master's field holds: a wagon whose merge is clean rides and the next is tried onto the result; one that
conflicts is left out with its files, and the trial goes on without it. No file is soft any more: the carrier is
code, and nothing resolves a conflict for a foreman (D10), except one only in generated files, which the train
writes again (generated.py, hal2 plan 0313 step 8).
"""

import subprocess


def git(repo: str, *args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout.strip()


def merge(repo: str, ours: str, theirs: str) -> tuple[str | None, list[str]]:
    """The commit of `theirs` merged into `ours` and the files that conflict; (None, []) when git cannot say."""
    code, out = git(repo, "merge-tree", "--write-tree", "--name-only", "--no-messages", ours, theirs)
    lines = out.split("\n") if out else []
    if code not in (0, 1) or not lines:
        return None, []
    made, commit = git(repo, "-c", "user.name=wagon-master", "-c", "user.email=wagon-master@localhost",
                       "commit-tree", lines[0], "-p", ours, "-p", theirs, "-m", "wagon train trial")
    return (commit if made == 0 else None), [f for f in lines[1:] if f]

