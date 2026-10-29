"""A checkout's plan pointers, in either home (hal2 plan 0409 step 12, design A9), for every skill's script.

`CURRENT_PLAN` (what the checkout works on), `PREVIOUS_PLAN` (the plan a `--here` switch keeps) and `LEAD` (a
servant's marker `<foreman's field> <plan> <step>`) live in the checkout's own git dir, `<git-dir>/hal/<name>` (what
`git rev-parse --git-path hal/<name>` names: per worktree, never committed, never in a `.gitignore`); the files home's
old place `<root>/plans/<name>` is read when the git dir has none. A write goes to the git dir only when the farm keeps
its plans in the store (`home = store`, planread.is_store), else to `plans/<name>` as before; either write removes the
other place's file, so no stale copy shadows it. A removal removes both. No process for a read: the git dir comes from the checkout's `.git`.

    path(root, name)    -> the file holding it now (the git dir's, else the old place, which may not exist)
    read(root, name)    -> its text stripped, "" when there is none
    exists(root, name)  -> it is set in either place
    target(root, name)  -> where a write goes (the home decides)
    write(root, name, text), remove(root, name)

Shell: `pointers.py read|path|exists|write|remove <root> <name> [<text>]` (read prints the text, path the file, exists
exits 0 or 1, write prints the file written).

Another skill loads this file by its path (skillpath.load("plan", "pointers"), or importlib), never this folder on
sys.path. `root` is the checkout's top folder (another field's too).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

CURRENT_PLAN = "CURRENT_PLAN"
PREVIOUS_PLAN = "PREVIOUS_PLAN"
LEAD = "LEAD"
NAMES = (CURRENT_PLAN, PREVIOUS_PLAN, LEAD)
SUBDIR = "hal"


def git_dir(root: Path | str) -> Path | None:
    """The git dir of the checkout `root` (its `.git` folder, or the folder a worktree's `.git` file names); None for
    no checkout. `root` itself, not a parent: a field's pointers are its own."""
    dot = Path(root) / ".git"
    if dot.is_dir():
        return dot
    try:
        text = dot.read_text(encoding="utf-8").strip() if dot.is_file() else ""
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    found = Path(text.removeprefix("gitdir:").strip())
    return found if found.is_absolute() else (Path(root) / found).resolve()


def git_path(root: Path | str, name: str) -> Path | None:
    """`<git-dir>/hal/<name>`; None for no checkout."""
    found = git_dir(root)
    return found / SUBDIR / name if found else None


def tree_path(root: Path | str, name: str) -> Path:
    """The files home's old place, `<root>/plans/<name>`."""
    return Path(root) / "plans" / name


def path(root: Path | str, name: str) -> Path:
    """The file that holds the pointer now: the git dir's when it exists, else the old place."""
    new = git_path(root, name)
    return new if new is not None and new.is_file() else tree_path(root, name)


def exists(root: Path | str, name: str) -> bool:
    return path(root, name).is_file()


def read(root: Path | str, name: str) -> str:
    """The pointer's text, stripped; "" when neither place has it or it cannot be read."""
    try:
        return path(root, name).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _planread():
    if "planread" not in sys.modules:
        spec = importlib.util.spec_from_file_location("planread", Path(__file__).resolve().parent / "planread.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["planread"] = module
        spec.loader.exec_module(module)
    return sys.modules["planread"]


def in_store(root: Path | str) -> bool:
    """The checkout's farm keeps its plans in the store (a write goes to the git dir); never raises."""
    try:
        return bool(_planread().is_store(Path(root)))
    except Exception:  # noqa: BLE001 - no CLI, a bad answer: the files home
        return False


def target(root: Path | str, name: str) -> Path:
    """Where a write of the pointer goes: the git dir in the store home, else the old place."""
    new = git_path(root, name)
    return new if new is not None and in_store(root) else tree_path(root, name)


def write(root: Path | str, name: str, text: str) -> Path:
    """Writes the pointer (a trailing newline added) where the home puts it; a git-dir write removes the old file.
    The file written."""
    place = target(root, name)
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    other = tree_path(root, name) if place != tree_path(root, name) else git_path(root, name)
    if other is not None:
        other.unlink(missing_ok=True)  # never a stale copy that shadows the one written
    return place


def remove(root: Path | str, name: str) -> None:
    """Removes the pointer from both places; a missing one is fine."""
    new = git_path(root, name)
    if new is not None:
        new.unlink(missing_ok=True)
    tree_path(root, name).unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[0] not in ("read", "path", "exists", "write", "remove") or argv[2] not in NAMES:
        print("usage: pointers.py read|path|exists|write|remove <root> CURRENT_PLAN|PREVIOUS_PLAN|LEAD [<text>]",
              file=sys.stderr)
        return 2
    verb, root, name = argv[:3]
    if verb == "read":
        if (text := read(root, name)):
            print(text)
    elif verb == "path":
        print(path(root, name))
    elif verb == "exists":
        return 0 if exists(root, name) else 1
    elif verb == "write":
        print(write(root, name, argv[3] if len(argv) > 3 else ""))
    else:
        remove(root, name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
