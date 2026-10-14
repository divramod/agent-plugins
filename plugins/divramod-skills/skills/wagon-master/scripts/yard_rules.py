"""The yard job's rules by name (hal2 plan 0294 step 8, D15): what a path's name alone says, no git and no file
read. `yard.sort` asks them first, in this order:

  secret  secret-shaped, as `/mtm`'s step 2 sorts them: `.env*`, `*_SEC`, keys and certificates by ending or name
          (SECRET), and a name holding `secret`, `token` or `credential`. The words count only for a file the barn
          does not track yet: a name the barn has was judged when it came in (docs/secrets.md, the encrypted
          `.secrets/*_SEC.secret`), the patterns count for every path
  junk    build output, an editor's or the system's file (JUNK_DIRS, JUNK): only a file the barn does not track,
          and never below a folder the barn tracks (`build/` holds sources in some units). A junk folder is named
          once, as the folder
  root    the path's top-level entry is not in the root allowlist: the names in backticks that open each bullet of
          the Decision of `.adr/repo-root-allowlist.md`, as the record holds it (`allowlist`)
"""

import fnmatch
import re

RECORD = ".adr/repo-root-allowlist.md"
SECRET = (".env*", "*_sec", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "id_ecdsa*")
SECRET_WORDS = ("secret", "token", "credential")
JUNK_DIRS = frozenset((
    "node_modules", "target", "dist", "build", ".build", "__pycache__", "DerivedData", "coverage", ".cache",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".gradle", ".next", ".turbo", ".venv", "venv", ".idea",
    ".vscode"))
JUNK = (".ds_store", "thumbs.db", "desktop.ini", "*.swp", "*.swo", "*~", ".#*", "#*#", "*.orig", "*.rej", "*.bak",
        "*.tmp", "*.log", "*.pyc", "*.pyo", "*.o", "*.class")
NAME, REMARK, NEXT = re.compile(r"`([^`\n]+)`"), re.compile(r"\s*\("), re.compile(r",\s+|\s+and\s+")


def secret(path: str, known: bool) -> bool:
    """Secret-shaped by its name; `known`: the barn tracks the path already."""
    name = path.rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatchcase(name, p) for p in SECRET) or (not known and any(w in name for w in SECRET_WORDS))


def junk(path: str) -> str | None:
    """The junk a path is part of: its junk folder (with `/`), or the file itself; None for work."""
    parts = path.split("/")
    for n, part in enumerate(parts[:-1]):
        if part in JUNK_DIRS:
            return "/".join(parts[:n + 1]) + "/"
    return path if any(fnmatch.fnmatchcase(parts[-1].lower(), p) for p in JUNK) else None


def after_remark(text: str, pos: int) -> int:
    """Past the remark in brackets that may follow a name (` (symlink to ...)`), nested brackets included."""
    m = REMARK.match(text, pos)
    if not m:
        return pos
    depth, pos = 1, m.end()
    while pos < len(text) and depth:
        depth += {"(": 1, ")": -1}.get(text[pos], 0)
        pos += 1
    return pos


def allowlist(record: str) -> set[str]:
    """The top-level entries the record allows: of each bullet of its Decision the names in backticks it opens
    with (`a`, `b` (a remark) and `c`: ...), each cut to its first path segment (`code/<language>/...` is `code`)."""
    decision = re.search(r"^## Decision\n(.*?)(?=^## |\Z)", record, re.S | re.M)
    out: set[str] = set()
    for bullet in re.split(r"^- ", decision.group(1) if decision else "", flags=re.M)[1:]:
        pos = 0
        while name := NAME.match(bullet, pos):
            out.add(name.group(1).split("/")[0])
            more = NEXT.match(bullet, after_remark(bullet, name.end()))
            if not more:
                break
            pos = more.end()
    return out


def named(path: str, known: bool, roots: set[str], tracked: set[str]) -> tuple[str, str] | None:
    """Why the name keeps a path in the yard, as (what to name, why), or None. `known`: the barn tracks the path;
    `roots`: the allowed top-level entries; `tracked`: the junk-named folders the barn tracks."""
    if secret(path, known):
        return path, "secret-shaped"
    part = None if known else junk(path)
    if part and part.rstrip("/") not in tracked:
        return part, "junk (build output, an editor's or the system's file)"
    root = path.split("/", 1)[0]
    if root not in roots:
        return root + ("/" if "/" in path else ""), f"`{root}` is no entry of the root allowlist ({RECORD})"
    return None
