"""Which worktrees of a repository are fields (hal2 plan 0490 step 11): the merge-to-main scan's orphan and
work-not-queued findings count only these.

A field lies in the farm's field root, `<home>/.hal/git/worktree/<main checkout's folder>/` (roles.slot_dir), or
beside or inside the main checkout (an older layout, and the scan's tests); an agent's scratch worktree elsewhere (a
`/private/tmp` scratchpad: L89, its "trial" woke the tollman as an orphan) is none. A standing train's worktree (branch `tollman-train-*`, also at another path: L96, an orphan "trainfix") is the
tollman's, never an orphan.
"""

from pathlib import Path

TRAIN = "tollman-train-"


def is_field(w: dict, main: str) -> bool:
    """`w`: a `git worktree list` entry {path, branch}; `main`: the main checkout."""
    path, home = Path(w["path"]), Path(main)
    root = path.parent
    in_root = root.name == home.name and root.parent.name == "worktree" and root.parent.parent.name == "git" \
        and root.parent.parent.parent.name == ".hal"
    return (in_root or root in (home, home.parent)) and not str(w.get("branch") or "").startswith(TRAIN) and not path.name.startswith(TRAIN)
