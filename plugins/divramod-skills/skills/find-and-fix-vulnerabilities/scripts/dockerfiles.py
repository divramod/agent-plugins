"""Base images named by the FROM lines of the Dockerfiles under the farms (ARG defaults resolved when simple)."""
import os
import re
from pathlib import Path

SKIP_DIRS = {"node_modules", ".git", "target"}
FROM = re.compile(r"^FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?\s*$", re.I)
ARG = re.compile(r"^ARG\s+([A-Za-z_][A-Za-z0-9_]*)(?:=(.*))?\s*$")
VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def is_dockerfile(name: str) -> bool:
    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".Dockerfile")


def find_dockerfiles(farm: Path) -> list:
    out = []
    for dirpath, dirnames, filenames in os.walk(farm):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        out += [Path(dirpath) / n for n in sorted(filenames) if is_dockerfile(n)]
    return out


def _resolve(ref: str, args: dict):
    """The reference with its variables replaced, or None when one has no value."""
    missing = []

    def sub(m):
        name = m.group(1) or m.group(3)
        value = args.get(name, m.group(2))
        if value is None:
            missing.append(name)
            return ""
        return value.strip("\"'")
    out = VAR.sub(sub, ref)
    return None if missing else out


def parse(text: str) -> tuple:
    """(images, unresolved): the external images of the FROM lines, and the references left with an unknown ARG."""
    args, stages, images, unresolved, seen_from = {}, set(), [], [], False
    for raw in text.splitlines():
        line = raw.strip()
        m = ARG.match(line)
        if m and not seen_from:  # only the ARGs before the first FROM are visible in a FROM line
            if m.group(2) is not None:
                args[m.group(1)] = m.group(2).strip()
            continue
        m = FROM.match(line)
        if not m:
            continue
        seen_from = True
        ref = _resolve(m.group(1), args)
        if ref is None:
            unresolved.append(m.group(1))
        elif ref.lower() != "scratch" and ref.lower() not in stages:
            images.append(ref)
        if m.group(2):
            stages.add(m.group(2).lower())
    return images, unresolved
