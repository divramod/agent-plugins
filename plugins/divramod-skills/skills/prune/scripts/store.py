"""The farm's prune state folder (hal2 plan 0377, D9, D14, D22): the size cache, the removal journal and the farm lock.

`$HAL_PRUNE_DIR/<repo>` when set (tests), else `~/.hal/prune/<repo>`, `<repo>` the main checkout's folder name. The
folder holds only what a run writes while running (caches, the lock): nothing in it is committed.
"""

import contextlib
import json
import os
import time
from pathlib import Path

LOCK, HOLDER = "lock", "lock.json"


class Locked(Exception):
    """Another prune run of this farm holds the lock (D14); its text names the holder."""


def state_dir(main: str | Path) -> Path:
    root = Path(os.environ.get("HAL_PRUNE_DIR") or Path.home() / ".hal/prune")
    d = root / Path(main).name
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path: Path, default):
    """The JSON file's content, `default` when it is missing or unreadable (a cache is never worth a crash)."""
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    """Atomically: a reader (a second run) never sees half a file."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    tmp.replace(path)


def _try_lock(fd: int) -> bool:
    """The OS's exclusive lock on `fd`, without waiting; the OS drops it when its process dies, so a dead holder's lock
    is taken over without a stale-lock race."""
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


@contextlib.contextmanager
def farm_lock(main: str | Path):
    """One prune run per farm at a time (D14): raises Locked naming the holder (its pid and start) when another run
    holds it; the holder's file is the only thing written, the lock goes with the process."""
    d = state_dir(main)
    fd = os.open(d / LOCK, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if not _try_lock(fd):
            h = read_json(d / HOLDER, {})
            raise Locked(f"pid {h.get('pid', '?')} since {h.get('started', '?')}")
        write_json(d / HOLDER, {"pid": os.getpid(), "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the lock
