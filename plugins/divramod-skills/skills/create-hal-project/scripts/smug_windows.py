"""A project's window in a smug yml (`~/.config/smug/<file>`), found or appended as text, never parsed YAML.

A window named by the alias or rooted at `~/a/<name>` exists already and is kept. Otherwise the new window copies the
file's last project window (root `~/a/<x>` that no other window has) with its name, root and the old folder renamed
(`/x`, `-x`, so `cd ~/.hal/git/worktree/x` and `farmer-x` follow) and `focus:` dropped; a file without one gets a
minimal window in the file's own indentation. The file is edited only, never committed.
"""
from __future__ import annotations

import re
from pathlib import Path

NAME = re.compile(r"^(\s*)- name:\s*['\"]?([^'\"#\s]+)")
ROOT = re.compile(r"^\s*root:\s*['\"]?([^'\"#\s]+)")


def windows(text: str) -> list[dict]:
    """The `- name:` blocks: name, root, indent, lines (trailing blank and comment lines left out)."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if NAME.match(line)]
    out = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = lines[start:end]
        while block and (not block[-1].strip() or block[-1].lstrip().startswith("#")):
            block.pop()
        m = NAME.match(block[0])
        root = next((r.group(1) for r in map(ROOT.match, block[1:]) if r), "")
        out.append({"name": m.group(2), "root": root.rstrip("/"), "indent": m.group(1), "lines": block})
    return out


def _same_root(root: str, name: str, home: Path) -> bool:
    return root in (f"~/a/{name}", f"$HOME/a/{name}", str(home / "a" / name))


def find(text: str, name: str, alias: str, home: Path) -> str | None:
    """The existing window's name when one is named by the alias or rooted at ~/a/<name>."""
    for w in windows(text):
        if w["name"] == alias or _same_root(w["root"], name, home):
            return w["name"]
    return None


def new_window(text: str, name: str, alias: str) -> list[str]:
    ws = windows(text)
    roots = [w["root"] for w in ws]
    projects = [w for w in ws if w["root"].startswith("~/a/") and roots.count(w["root"]) == 1
                and "/" not in w["root"][4:]]
    if projects:
        model = projects[-1]
        old = re.escape(model["root"][4:])
        rename = re.compile(rf"(?<=[/'\"-]){old}(?![\w.-])")
        out = []
        for line in model["lines"]:
            if re.match(r"^\s*focus:", line):
                continue
            if NAME.match(line):
                line = f"{model['indent']}- name: {alias}"
            out.append(rename.sub(name, line))
        return out
    pad = ws[0]["indent"] if ws else "  "
    return [f"{pad}- name: {alias}", f"{pad}  root: ~/a/{name}", f"{pad}  layout: even-horizontal",
            f"{pad}  commands:", f"{pad}    -", f"{pad}  panes:", f"{pad}    - commands:", f"{pad}      - sl"]


def plan(path: Path, name: str, alias: str, home: Path) -> dict:
    """The smug action of one yml: exists (with the window's name), skip (no such file) or create."""
    action = {"kind": "smug", "target": str(path)}
    if not path.is_file():
        return {**action, "state": "skip", "detail": "no such file"}
    text = path.read_text()
    found = find(text, name, alias, home)
    if found:
        return {**action, "state": "exists", "detail": f"window {found}"}
    if not windows(text):
        return {**action, "state": "skip", "detail": "no windows: list to append to"}
    return {**action, "state": "create", "detail": f"window {alias}, root ~/a/{name}"}


def append(path: Path, name: str, alias: str) -> None:
    text = path.read_text()
    block = "\n".join(new_window(text, name, alias))
    path.write_text(text.rstrip("\n") + "\n\n" + block + "\n")
