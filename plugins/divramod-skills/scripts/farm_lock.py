#!/usr/bin/env python3
"""A farm lock names its holder (hal2 plan 0561, decisions D1, D9-D11): the Python side of `hal2_core::farm_lock`.

A lock file that processes of different fields of a farm take for a short critical section (the plan numbers, the
tollman's board, the daybook, the tests' git seed) holds one JSON line, the holder's record
`{"schema":1,"pid":4242,"taken":"2026-10-31T21:07:03Z"}`, written after the holder has the lock. A freezer (the
workqueue's `freeze`) finds a holder by trying the lock and, when that fails, reading the record; it spares the
holder's process tree until the lock is released, so no field's freeze stops a process others wait behind. The record
is pinned with the Rust writer by `hal2-core/tests/fixtures/farm_lock.json` (`test_farm_lock.py`).

  from farm_lock import hold, probe
  with hold(folder / "plan-numbers.json.lock"):        # blocking; hold(path, wait=5) raises TimeoutError
      ...                                              # the file now names this process
  probe(path)                                          # Probe(held=True, record={...}) while somebody holds it

Take: announce it with the intent file `<lock>.<pid>` (D16), open read-write, create (0600), NEVER truncate on open
(a waiter would wipe the holder's record, D11), lock, `ftruncate(0)`, write the line. Release: `ftruncate(0)` while
still held (D15: no stale record names a process that no longer holds it), unlock, close, remove the intent. A freezer
that finds the lock held but unnamed (its holder stopped between take and record) spares every live pid with an
intent file; it removes the intents of dead pids.
Unix: `flock` of the whole file (what Rust's `File::lock` takes too). Windows (D10): one byte at `WINDOWS_BYTE` by
`msvcrt.locking`, so the record stays readable; it overlaps a whole-file lock, so an older holder still excludes this
one (its record unreadable: an unnamed holder). The daybook's exclusive-create lock (held while its file exists)
carries the same record: `create_exclusive` (its intent goes once the record is written: the release is the caller's
unlink), `exclusive_stale`. A caller of the low-level `open_lock`, `lock`, `name` releases with `release(fd)`.

A reader trusts the pid only while that process started before `taken` (+ `START_SLACK_S`): a reused pid started
later. Python reads a start with `ps -o etime=` (once per contended probe, never on a free lock).
"""
import calendar
import json
import os
import subprocess
import time
from datetime import datetime
from typing import NamedTuple

SCHEMA = 1
WINDOWS_BYTE = 0x4000_0000  # a Windows holder locks this one byte, far past any record
START_SLACK_S = 2  # taken is cut to the second and a start is derived: a holder may start this much after it
RETRY_S = 0.01  # between tries of a bounded take
READ_MAX = 4096  # a record is one short line
UNKNOWN = object()  # a pid's start that cannot be read here (no ps, Windows): trust nothing, fall back to the age

if os.name == "nt":  # pragma: no cover - the Windows branch is exercised on Windows only
    import msvcrt
else:
    import fcntl


class Probe(NamedTuple):
    held: bool
    record: dict | None  # the trusted holder's record, None for a free lock or an unnamed holder


def utc(now: float | None = None) -> str:
    """RFC 3339 UTC with `Z`, whole seconds."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if now is None else now))


def line(pid: int | None = None, now: float | None = None) -> str:
    """The record's file content: compact JSON, whole seconds, a newline after it."""
    return json.dumps({"schema": SCHEMA, "pid": os.getpid() if pid is None else pid, "taken": utc(now)},
                      separators=(",", ":")) + "\n"


def parse(text: str) -> dict | None:
    """The record of a lock file's text; None for anything else (empty, torn, another schema, pid 0, no time)."""
    try:
        record = json.loads(text.strip())
        taken = record["taken"]
        valid = (isinstance(record, dict) and record.get("schema") == SCHEMA
                 and isinstance(record["pid"], int) and not isinstance(record["pid"], bool) and record["pid"] > 0
                 and isinstance(taken, str))
        return {**record, "taken_s": epoch(taken)} if valid else None
    except (ValueError, KeyError, TypeError):
        return None


def epoch(taken: str) -> int:
    """Seconds since the epoch of an RFC 3339 time (`Z` or an offset); ValueError when it is none."""
    try:
        return calendar.timegm(time.strptime(taken, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        stamp = datetime.fromisoformat(taken)
        if stamp.tzinfo is None:
            raise
        return int(stamp.timestamp())


def trusts(record: dict, start) -> bool:
    """Whether a process started at `start` (epoch seconds) is the one that wrote `record`: it started before
    `taken`. None (no such process), UNKNOWN and 0 are not."""
    return isinstance(start, int) and 0 < start <= record["taken_s"] + START_SLACK_S


def pid_start(pid: int):
    """When the live process `pid` started (epoch seconds), None when there is none, UNKNOWN when this system cannot
    say (Windows, no `ps`)."""
    if os.name == "nt":
        return UNKNOWN
    try:
        out = subprocess.run(["ps", "-o", "etime=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    text = out.stdout.strip()
    if out.returncode != 0 or not text:
        return None if out.returncode == 1 else UNKNOWN
    try:
        days, _, clock = text.rpartition("-")
        parts = [int(p) for p in clock.split(":")]
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + part
        return int(time.time()) - seconds - (int(days) * 86400 if days else 0)
    except ValueError:
        return UNKNOWN


def _try_lock(fd: int) -> bool:
    """Take the lock without waiting; False when somebody holds it."""
    if os.name == "nt":  # pragma: no cover
        os.lseek(fd, WINDOWS_BYTE, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _unlock(fd: int) -> None:
    if os.name == "nt":  # pragma: no cover
        os.lseek(fd, WINDOWS_BYTE, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        os.lseek(fd, 0, os.SEEK_SET)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def lock(fd: int, wait: float | None = None) -> bool:
    """Take the lock on `fd`: wait for ever (None) or up to `wait` seconds; False when still held by then."""
    if wait is None and os.name != "nt":
        fcntl.flock(fd, fcntl.LOCK_EX)
        return True
    end = None if wait is None else time.monotonic() + wait
    while not _try_lock(fd):
        if end is not None and time.monotonic() >= end:
            return False
        time.sleep(RETRY_S)
    return True


def name(fd: int, pid: int | None = None, now: float | None = None) -> None:
    """Write this process's record into the lock file `fd`, which the caller holds: empty it first, then one write."""
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, line(pid, now).encode())


def open_lock(path, parents: bool = True) -> int:
    """Open (create) the lock file without truncating it, its folders made unless `parents` is False (then a missing
    folder is a FileNotFoundError, for a caller whose folder may be removed under it)."""
    if parents:
        os.makedirs(os.path.dirname(os.fspath(path)) or ".", exist_ok=True)
    return os.open(path, os.O_RDWR | os.O_CREAT, 0o600)


_takes: dict[str, int] = {}  # this process's live takes per intent file: nested takes remove it at the last


def intent_path(path, pid: int | None = None) -> str:
    """The intent file of `pid` (this process) for the lock `path`: `<lock>.<pid>` beside it."""
    return f"{os.fspath(path)}.{os.getpid() if pid is None else pid}"


def intend(path) -> str:
    """Announce this process's take of the lock `path` (its folder must exist): write `<lock>.<pid>` (the record line
    in it, for a reader by hand; its time is the announcement's). Returns the intent file for `unintend`."""
    intent = intent_path(path)
    fd = os.open(intent, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, line().encode())
    finally:
        os.close(fd)
    _takes[intent] = _takes.get(intent, 0) + 1
    return intent


def unintend(intent: str) -> None:
    """Withdraw an announcement of `intend`: the file goes with this process's last take of that lock."""
    left = _takes.get(intent, 1) - 1
    if left > 0:
        _takes[intent] = left
        return
    _takes.pop(intent, None)
    try:
        os.unlink(intent)
    except OSError:
        pass  # gone already, or a dead pid's file for the sweep later


def release(fd: int) -> None:
    """Release the lock held on `fd`: empty the record while still holding it (D15), unlock, close."""
    try:
        os.ftruncate(fd, 0)
    except OSError:
        pass
    try:
        _unlock(fd)
    except OSError:
        pass
    os.close(fd)  # closing releases the lock too


class Held:
    """A lock taken by `hold`; a context manager. `fd` is open while held; leaving it closes, which releases."""

    def __init__(self, path, fd: int, intent: str | None = None):
        self.path, self.fd, self.intent = path, fd, intent

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()

    def release(self) -> None:
        if self.fd is not None:
            release(self.fd)
            self.fd = None
        if self.intent is not None:
            unintend(self.intent)
            self.intent = None


def hold(path, wait: float | None = None) -> Held:
    """Take the farm lock at `path`, naming this process in it: wait for ever (None) or up to `wait` seconds, then
    TimeoutError. Use as `with hold(path):`. The take is announced first (D16) and withdrawn after the release."""
    os.makedirs(os.path.dirname(os.fspath(path)) or ".", exist_ok=True)
    intent = intend(path)
    try:
        fd = open_lock(path)
    except BaseException:
        unintend(intent)
        raise
    try:
        if not lock(fd, wait):
            raise TimeoutError(f"the lock {path} was not taken in {wait:g} s")
        name(fd)
    except BaseException:
        os.close(fd)
        unintend(intent)
        raise
    return Held(path, fd, intent)


def probe(path, start_of=pid_start) -> Probe:
    """Whether the flock `path` is held and by whom, `start_of` giving a pid's start. Read-only: a missing file is
    free and never created; a free lock is taken and released at once."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return Probe(False, None)
    try:
        if _try_lock(fd):
            _unlock(fd)
            return Probe(False, None)
        return Probe(True, _named(fd, start_of))
    finally:
        os.close(fd)


def _named(fd: int, start_of) -> dict | None:
    """The trusted record of an open lock file, None when it has none or its pid is not the holder."""
    os.lseek(fd, 0, os.SEEK_SET)
    record = parse(os.read(fd, READ_MAX).decode("utf-8", "replace"))
    return record if record and trusts(record, start_of(record["pid"])) else None


def create_exclusive(path, pid: int | None = None) -> bool:
    """Take an exclusive-create lock (O_CREAT|O_EXCL: held while the file exists) and write the record into it;
    False when the file exists. The take is announced (D16) until the record is written: a holder stopped between
    the create and the write is still found."""
    intent = intend(path)
    try:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        try:
            os.write(fd, line(pid).encode())
        finally:
            os.close(fd)
        return True
    finally:
        unintend(intent)


def exclusive_stale(path, max_age: float, start_of=pid_start) -> bool:
    """Whether the exclusive-create lock `path` was left by a holder that is gone. With a record: stale when its
    pid is no process or one that started after `taken` (a reused pid), never by age, so a frozen holder keeps its
    lock. Without one (a holder of before this contract, or one that has not written yet): stale past `max_age`
    seconds since the file was last written. Where a pid's start cannot be read, by age alone."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            record = parse(handle.read(READ_MAX))
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return False
    if record is None:
        return age > max_age
    start = start_of(record["pid"])
    if start is UNKNOWN:
        return age > max_age
    return not trusts(record, start)
