"""The pretest's green markers (hal2 plan 0349 step 28, D75), the gate's own markers kept on the Mac: an empty file
`gate-<job>-<key>` in `cache/pretest/` of the folder it is given (the wagon master's role folder: its cache class
under CACHEDIR.TAG, declared in manifest.toml, never checked), written only after a green run of a clean field. A
marker older than KEEP_DAYS goes at every pretest. Every write here may fail without a word: a marker is only a
cache, and no failure of it may turn a result into another (pretest.py).
"""

import contextlib
import subprocess
import time
from pathlib import Path

MARKERS = Path("cache/pretest")
KEEP_DAYS = 14
TAG = "Signature: 8a477f597d28d172789f06886806bc55\n# the wagon master's pretest markers (scripts/pretest_markers.py)\n"


def folder(state: Path, now: float | None = None) -> Path | None:
    """The markers' folder below `state`, created with its CACHEDIR.TAG and pruned; None when it cannot be made."""
    where = state / MARKERS
    try:
        where.mkdir(parents=True, exist_ok=True)
        tag = where.parent / "CACHEDIR.TAG"
        if not tag.exists():
            tag.write_text(TAG)
    except OSError:
        return None
    prune(where, now)
    return where


def prune(where: Path, now: float | None = None) -> None:
    """The markers past KEEP_DAYS dropped; one that goes meanwhile (another pretest's prune) is no error."""
    edge = (now or time.time()) - KEEP_DAYS * 86400
    with contextlib.suppress(OSError):
        for f in list(where.iterdir()):
            with contextlib.suppress(OSError):
                if f.is_file() and f.stat().st_mtime < edge:
                    f.unlink(missing_ok=True)


def name(job: str, key: str) -> str:
    return f"gate-{job}-{key}"


def cached(where: Path | None, job: str, key: str | None) -> bool:
    return bool(where and key) and (where / name(job, key)).exists()


def mark(where: Path | None, job: str, key: str | None) -> None:
    if where and key:
        with contextlib.suppress(OSError):
            (where / name(job, key)).touch()


def dirty(top: str) -> list[str]:
    """The tracked files the field `top` holds changed (`git status`): a key is HEAD's committed content, so a dirty
    field writes no marker, and a job that changed tracked files leaves a tree merge-to-main would refuse."""
    try:
        p = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=top, capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [f"(git status: {e})"]
    if p.returncode:
        return [f"(git status ended {p.returncode})"]
    return [line[3:] for line in p.stdout.splitlines() if line.strip()]
