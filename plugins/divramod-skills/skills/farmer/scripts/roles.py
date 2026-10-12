"""Where a role works and keeps its files (hal2's .adr/roles-folder.md, hal2 plan 0143).

A role (the farmer, lord, i, chancellor, duke, king, pope, marshall) works in the worktree slot and branch
`<role>-<project>` of its repository (`farmer-hal2`), so two repositories' farmers never share a session name.
`<project>` is the origin remote's repository name, else the main checkout's folder name (lowercase; other
characters than letters, digits and `-` become `-`), as hal2_git::worktree::Layout computes it. The role file is
`roles/<role>/ROLE.md` (committed) and every runtime file of the role lives beside it in the slot's
`roles/<role>/`, ignored by the folder's own `.gitignore` (GITIGNORE). The farmer's state folder is that folder;
`FARMER_DIR` overrides it with `$FARMER_DIR/<main checkout's folder>` (tests, other machines).
"""

import os
import re
import subprocess
from pathlib import Path

ROLES = ("farmer", "lord", "i", "chancellor", "duke", "king", "pope", "marshall")
ROLE = "farmer"
ROLE_FILE = f"roles/{ROLE}/ROLE.md"
ROLE_IGNORE = f"roles/{ROLE}/.gitignore"
GITIGNORE = ("# The role's folder (hal2 .adr/roles-folder.md): ROLE.md is committed, every runtime file is ignored.\n"
             "*\n!.gitignore\n!ROLE.md\n")
OVERRIDE = Path(os.environ["FARMER_DIR"]) if os.environ.get("FARMER_DIR") else None
LEGACY = Path.home() / "skills" / "farmer"  # the state root before plan 0143: <LEGACY>/<repo>/


def git(repo: str | Path, *args: str) -> str:
    try:
        p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def main_checkout(repo: str | Path) -> Path:
    """The main checkout of the repository containing `repo` (`repo` itself outside git)."""
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common).parent if common else Path(repo)


def project_of(text: str) -> str | None:
    """A project name from a remote URL or a folder name: its last segment without `.git`, made a slot name part."""
    last = re.split(r"[/:]", text.strip().rstrip("/"))[-1]
    last = last[:-4] if last.endswith(".git") else last
    name = re.sub(r"[^a-z0-9-]", "-", last.lower()).strip("-")
    return name or None


def project(repo: str | Path) -> str:
    """The repository's project name: origin's repository name, else the main checkout's folder."""
    main = main_checkout(repo)
    return project_of(git(main, "remote", "get-url", "origin")) or project_of(main.name) or main.name


def slot_name(repo: str | Path, role: str = ROLE) -> str:
    return f"{role}-{project(repo)}"


def slot_dir(repo: str | Path, role: str = ROLE, home: Path | None = None) -> Path:
    """`~/.hal/git/worktree/<main checkout's folder>/<role>-<project>` (it may not exist)."""
    return (home or Path.home()) / ".hal/git/worktree" / main_checkout(repo).name / slot_name(repo, role)


def is_slot(top: str | Path, role: str = ROLE) -> bool:
    """Whether the checkout `top` is the repository's slot of `role`."""
    return Path(top).name == slot_name(top, role)


def state_dir(repo: str | Path, override: Path | None = None, role: str = ROLE) -> Path:
    """The role's state folder: `$FARMER_DIR/<repo>` with an override, else `roles/<role>/` of the role's slot.
    The slot folder itself is never created here (it would block `git worktree add`): without a slot the path is
    returned as it is, reading it finds nothing. A new role folder gets the GITIGNORE."""
    if override is not None:
        d = override / main_checkout(repo).name
        d.mkdir(parents=True, exist_ok=True)
        return d
    slot = slot_dir(repo, role)
    d = slot / "roles" / role
    if slot.is_dir():
        d.mkdir(parents=True, exist_ok=True)
        if not (d / ".gitignore").exists():
            (d / ".gitignore").write_text(GITIGNORE)
    return d


def is_farmer_label(slot: str) -> bool:
    """Whether an action's or the agents list's slot label is the farmer's own slot (`farmer-<project>`, or the
    unmigrated `farmer`)."""
    return slot == ROLE or slot.startswith(ROLE + "-")
