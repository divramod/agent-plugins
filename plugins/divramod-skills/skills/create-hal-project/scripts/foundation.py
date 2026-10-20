"""The foundation of a new hal repo beyond the flat templates: gate, pre-push, .hal/, publishable basics, layout.

templates/tree/<path>.tmpl is the file <path> of the new repo ({name} and {alias} replaced, as in the flat
templates); KEEP_DIRS are the hal folders that get a .gitkeep (plan 0408 D3); EXECUTABLE the files written 0755;
INSTALL the call that installs the pre-push hook in the checkout, run from its root after the first commit.
"""
from __future__ import annotations

from pathlib import Path

TREE = Path(__file__).resolve().parent.parent / "templates" / "tree"
KEEP_DIRS = ("code", "docs", "designs", "plans", "research", "roles", ".adr", "utils", "workflows", "projects",
             "assets/logos", "shotfiles")
EXECUTABLE = frozenset({"code/bash/scripts/gate/main.sh", "code/bash/scripts/pre-push/main.sh"})
HOOK_MARK = "Written by code/bash/scripts/pre-push/main.sh --install"  # in the shim the install writes
INSTALL = ("bash", "code/bash/scripts/pre-push/main.sh", "--install")


def paths() -> list[str]:
    """Every path the foundation writes into the new repo, sorted: the tree's files, then the .gitkeeps."""
    tree = sorted(str(f.relative_to(TREE))[: -len(".tmpl")] for f in TREE.rglob("*.tmpl") if f.is_file())
    return tree + [f"{d}/.gitkeep" for d in KEEP_DIRS]


def render(path: str, name: str, alias: str) -> str:
    """The text of <path> in the new repo; a .gitkeep is empty."""
    if path.endswith("/.gitkeep"):
        return ""
    text = (TREE / f"{path}.tmpl").read_text()
    return text.replace("{name}", name).replace("{alias}", alias)


def files(name: str, alias: str) -> dict[str, tuple[str, bool]]:
    """path -> (text, executable) of every foundation file."""
    return {p: (render(p, name, alias), p in EXECUTABLE) for p in paths()}
