"""A test's git tree grown once per process and copied for every later test (the agents-test job's speed): test_farmer's
`Repo`, worktree_farm's `Slots` and the tollman's fields spent most of their time spawning `git` for the same commits.
No test here."""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_SEEDS = {}  # key -> (the seed's copy, the folder it was grown in: its real path, its path)
_ROOT = []


def grow(tmp, key, build):
    """Make the empty folder `tmp` hold the tree `build()` grows there: grown for real the first time per `key` and
    process, then copied from that first tree, every absolute path to its folder (worktree links, the origin's
    url) rewritten to `tmp`."""
    tmp = Path(tmp)
    if key not in _SEEDS:
        build()
        if not _ROOT:
            _ROOT.append(tempfile.mkdtemp(prefix="git-seed-"))
            atexit.register(shutil.rmtree, _ROOT[0], True)
        seed = Path(_ROOT[0]) / str(len(_SEEDS))
        shutil.copytree(tmp, seed, symlinks=True)
        _SEEDS[key] = (seed, [os.path.realpath(tmp), str(tmp)])
        return
    seed, first = _SEEDS[key]
    shutil.copytree(seed, tmp, symlinks=True, dirs_exist_ok=True)
    moves = zip(first, (os.path.realpath(tmp), str(tmp)))  # the real path first: /private/var holds /var
    _relocate(tmp, [(a.encode(), b.encode()) for a, b in moves])


def _relocate(top, moves):
    """Rewrite the old folder's paths in every git file that holds one (`.git` links, `gitdir`, `config`,
    `FETCH_HEAD`): objects and the index hold none."""
    for root, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if d not in ("objects", "hooks")]
        for name in files:
            if name == "index":
                continue
            path = os.path.join(root, name)
            if os.path.islink(path) or os.path.getsize(path) > 1 << 20:
                continue
            with open(path, "rb") as f:
                data = f.read()
            new = data
            for old, to in moves:
                new = new.replace(old, to)
            if new != data:
                with open(path, "wb") as f:
                    f.write(new)
