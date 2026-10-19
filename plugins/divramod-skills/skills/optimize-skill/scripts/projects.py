"""The per-cwd folders Claude Code leaves in its config folder, and their removal (plan 0390 step 6). Stdlib only.

Every headless run makes `<config>/projects/<slug of its cwd>/` (with `--no-session-persistence` only an empty
`memory/`; plan 0390 step 1's spike); config is `$CLAUDE_CONFIG_DIR`, else `~/.claude`. The slug is the cwd's
real path with every character but a letter or digit replaced by `-` (a real run made
`-private-tmp-...-scratchpad-ws-probe` for `/private/tmp/.../scratchpad/ws-probe`). A run notes which of its cwds'
folders are missing before it starts (`missing`) and removes those afterwards (`remove`), only while they hold
nothing but an empty `memory/`: a folder the user had, or one with anything in it, is never touched.
"""

import os
import re
from pathlib import Path

NON_WORD = re.compile(r"[^A-Za-z0-9]")


def config_dir(env=None):
    env = os.environ if env is None else env
    if env.get("CLAUDE_CONFIG_DIR"):
        return Path(env["CLAUDE_CONFIG_DIR"]).expanduser()
    return Path(env.get("HOME") or Path.home()).expanduser() / ".claude"


def slug(path):
    return NON_WORD.sub("-", str(path))


def folders(cwds, env=None):
    """The project folders the cwds would get (for the path as given and its real path)."""
    root = config_dir(env) / "projects"
    out = []
    for cwd in cwds:
        for form in (Path(cwd).absolute(), Path(cwd).resolve()):
            folder = root / slug(form)
            if folder not in out:
                out.append(folder)
    return out


def missing(cwds, env=None):
    """The cwds' project folders that do not exist yet (call before the run)."""
    return [folder for folder in folders(cwds, env) if not folder.exists()]


def _empty_but_memory(folder):
    entries = list(folder.iterdir())
    return all(entry.name == "memory" and entry.is_dir() and not entry.is_symlink() and not any(entry.iterdir())
               for entry in entries)


def remove(candidates):
    """Remove each folder of `candidates` (from `missing`) that holds at most an empty memory/; the removed ones."""
    removed = []
    for folder in candidates:
        try:
            if folder.is_dir() and not folder.is_symlink() and _empty_but_memory(folder):
                if (folder / "memory").is_dir():
                    (folder / "memory").rmdir()
                folder.rmdir()
                removed.append(str(folder))
        except OSError:
            continue
    return removed
