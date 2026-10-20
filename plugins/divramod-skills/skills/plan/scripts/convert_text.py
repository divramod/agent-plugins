"""Text helpers of `plan.py convert` (hal2 plan 0376, design §7): a Markdown body split into its `## ` sections (fences
respected), relative links rewritten when a file moves or a file it links to moves, and the plain mentions
`steps/<n>.md` of the plan folder's Markdown pointed at the converted step files.
"""
from __future__ import annotations

import os
import re

FENCE = re.compile(r"^\s*(```|~~~)")
LINK = re.compile(r"\]\(([^)\s]+)((?:\s[^)]*)?)\)")
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)


def sections(body: str) -> tuple[str, list[tuple[str, str]]]:
    """The text before the first `## ` heading and each `(heading, text)` after it, the text without its heading
    line; a `## ` inside a fenced block is text."""
    head, found, fenced = [], [], False
    for line in body.splitlines(keepends=True):
        if FENCE.match(line):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            found.append([line[3:].strip(), []])
        elif found:
            found[-1][1].append(line)
        else:
            head.append(line)
    return "".join(head), [(title, "".join(lines)) for title, lines in found]


def strip_blank(text: str) -> str:
    return text.strip("\n").rstrip() if text.strip() else ""


def join_sections(parts: list[tuple[str, str]]) -> str:
    """`## <heading>` and its text for each part, a blank line between."""
    return "".join(f"\n## {title}\n\n{strip_blank(text)}\n" for title, text in parts)


def one_line(text: str) -> str:
    """Front matter text: one line, never both kinds of quote (the subset has no escapes)."""
    text = " ".join(str(text).split())
    return text.replace('"', "'") if '"' in text and "'" in text else text


def cut(text: str, limit: int = 200) -> str:
    text = one_line(text)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def relative(target: str) -> bool:
    return bool(target) and not target.startswith(("#", "/")) and not SCHEME.match(target)


def moved_target(target: str, old_dir: str, new_dir: str, moves: dict[str, str]) -> str:
    """The link `target` written in a file once in `old_dir`, now in `new_dir` (paths relative to the plan folder,
    `""` its root); `moves` maps old paths to new ones."""
    path, mark, anchor = target.partition("#")
    if not relative(path):
        return target
    resolved = os.path.normpath(os.path.join(old_dir, path)).replace(os.sep, "/")
    landed = moves.get(resolved, resolved)
    if old_dir == new_dir and landed == resolved:
        return target
    return os.path.relpath(landed, new_dir or ".").replace(os.sep, "/") + mark + anchor


def rewrite_links(text: str, old_dir: str, new_dir: str, moves: dict[str, str]) -> str:
    """Every inline link's relative target outside fenced blocks re-pointed (see moved_target)."""
    out, fenced = [], False
    for line in text.splitlines(keepends=True):
        if FENCE.match(line):
            fenced = not fenced
        if not fenced and "](" in line:
            line = LINK.sub(lambda m: f"]({moved_target(m.group(1), old_dir, new_dir, moves)}{m.group(2)})", line)
        out.append(line)
    return "".join(out)


def rewrite_mentions(text: str, here: str, steps: dict[str, str]) -> str:
    """The plain mentions `steps/<id>.md` (not part of a longer path) in a file in the folder `here` pointed at the
    converted step files; `steps` maps a row id to its new path relative to the plan folder."""
    def swap(m):
        new = steps.get(m.group(1))
        return os.path.relpath(new, here or ".").replace(os.sep, "/") if new else m.group(0)
    return re.sub(r"(?<![\w/.-])steps/([A-Za-z0-9_-]+)\.md", swap, text)
