"""Which worktrees of a repository are fields (hal2 plan 0490 step 11): the merge-to-main scan's orphan and
work-not-queued findings count only these.

A field lies in the farm's field root, `<home>/.hal/git/worktree/<main checkout's folder>/` (roles.slot_dir), or
beside or inside the main checkout (an older layout, and the scan's tests); an agent's scratch worktree elsewhere (a
`/private/tmp` scratchpad: L89, its "trial" woke the tollman as an orphan) is none. A standing train's worktree (branch `tollman-train-*`, also at another path: L96, an orphan "trainfix") is the
tollman's, never an orphan. Plan 0604: so are the carrier `train-<n>-<a>`, the kept worktrees `tollman-train`,
`tollman-fix` and `<NN>-fix` (a foreman's fix or resolve branch `<NN>-train-<n>-<a>-fix|resolve` is checked out
there), and the tollman's own fix `tollman-train-<n>-<a>-fix`.
"""

import re
from pathlib import Path

TRAIN = "tollman-train"  # the kept carrier worktree, the legacy carriers `tollman-train-*`, the own fix branches
TRAIN_WORK = re.compile(r"^(train-\d+-\d+|\d{2}-fix|tollman-fix|\d{2}-train-\d+-\d+-(fix|resolve))$")


def is_field(w: dict, main: str) -> bool:
    """`w`: a `git worktree list` entry {path, branch}; `main`: the main checkout."""
    path, home = Path(w["path"]), Path(main)
    root = path.parent
    in_root = root.name == home.name and root.parent.name == "worktree" and root.parent.parent.name == "git" \
        and root.parent.parent.parent.name == ".hal"
    branch = str(w.get("branch") or "")
    train = branch.startswith(TRAIN) or path.name.startswith(TRAIN) or TRAIN_WORK.match(branch) or TRAIN_WORK.match(path.name)
    return (in_root or root in (home, home.parent)) and not train
