"""Code lines per file: scc's `code` count minus inline Rust test modules.

Blank and comment-only lines never count (scc knows each language's comments, doc comments and docstrings
included; tokei 14 counts Rust `///` as code, so it is not used). A Rust file's
`#[cfg(test)] mod <name> { ... }` blocks do not count either: hal2's small-files rule leaves tests out.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SOURCE_EXTENSIONS = {
    ".rs", ".swift", ".ts", ".tsx", ".js", ".mjs", ".lua", ".py", ".sh", ".bash", ".kt",
}

TEST_ATTRIBUTE = re.compile(r"^\s*#\[cfg\(test\)\]\s*$")
MOD_OPENING = re.compile(r"^\s*(pub(\([^)]*\))?\s+)?mod\s+\w+\s*\{")
STRING_OR_CHAR = re.compile(r'"(\\.|[^"\\])*"|\'(\\.|[^\'\\])\'')


def require_scc():
    """Exit 2 with the install command when scc is missing."""
    if shutil.which("scc") is None:
        print("fix-loc: scc is missing -> brew install scc (or run scripts/install-prerequisites.sh)", file=sys.stderr)
        sys.exit(2)


def scc_code_lines(root, paths):
    """{relative path: scc code lines} for `paths` (relative to `root`), counted in batches."""
    require_scc()
    counts = {}
    paths = list(paths)
    for start in range(0, len(paths), 500):
        batch = paths[start:start + 500]
        out = subprocess.run(
            ["scc", "--by-file", "--format", "json", "--no-gen", *batch],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout
        for language in json.loads(out or "[]"):
            for report in language.get("Files") or []:
                counts[str(Path(report["Location"]))] = report["Code"]
    return counts


def _code_line(line):
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("//")


def rust_test_lines(text):
    """Code lines inside the file's `#[cfg(test)] mod x { ... }` blocks (the braces matched)."""
    lines = text.splitlines()
    total, i = 0, 0
    while i < len(lines):
        if TEST_ATTRIBUTE.match(lines[i]):
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].strip().startswith("#[")):
                j += 1
            if j < len(lines) and MOD_OPENING.match(lines[j]):
                end = _block_end(lines, j)
                total += 1 + sum(_code_line(line) for line in lines[i + 1:end + 1])
                i = end + 1
                continue
        i += 1
    return total


def _block_end(lines, start):
    """Index of the line that closes the block opened on `lines[start]`."""
    depth, opened = 0, False
    for index in range(start, len(lines)):
        code = STRING_OR_CHAR.sub("", lines[index].split("//", 1)[0])
        depth += code.count("{") - code.count("}")
        opened = opened or "{" in code
        if opened and depth <= 0:
            return index
    return len(lines) - 1


def code_lines(root, paths):
    """{relative path: code lines} for the source files among `paths`, inline Rust tests left out."""
    root = Path(root)
    sources = [p for p in paths if Path(p).suffix in SOURCE_EXTENSIONS]
    counts = scc_code_lines(root, sources)
    for path in sources:
        if path.endswith(".rs") and path in counts:
            text = (root / path).read_text(errors="replace")
            if "#[cfg(test)]" in text:
                counts[path] = max(0, counts[path] - rust_test_lines(text))
    return counts
