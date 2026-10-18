"""The store (plan 0311 design.md, Store; D2, D4, D10, D16): `~/.config/hal2/lookout/<farm>.yaml` and `changes.jsonl`.

A farm's file is the daybook's `watches:` format, read and written only by the daybook's `watchfile.py` (imported
through `lookout_frame`, never copied, D4), plus the lookout keys of design.md. Every change the CLI makes (`add`,
`set`, `end`) appends one `changes.jsonl` line (at, by, farm, watch, op, changes {key: [old, new]}) before the record
is written, both under one file lock. The tick writes only the run keys `last_run`, `last_result`, `state` and, when
a check settles, the end of the watch; it takes the same lock only for that write (D10). Stdlib only.
"""

import getpass
import os
import re
import shutil
import socket
import tempfile
import time
from pathlib import Path

import lookout_frame  # noqa: F401  (the farmer's and the daybook's scripts on the import path)
import paths
import roles
import runner
import watchfile

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RUN_KEYS = ("last_run", "last_result", "state")
OPTIONAL = ("every", "until", "prompt", "judge", "apply", "model", "budget", "notify", "timeout")
EDITABLE = ("title", "cron", "check", "active") + OPTIONAL
BACKENDS = ("desktop", "telegram")
TICK_BY = "lookout tick"


class StoreError(ValueError):
    """A refused change; the message is for the user."""


class LockError(StoreError):
    pass


class Lock:
    """A lock file made by O_CREAT|O_EXCL (no `fcntl`: it must work on Windows too); stale after `stale` seconds."""

    def __init__(self, path, wait=5.0, stale=60.0):
        self.path, self.wait, self.stale, self.held = Path(path), wait, stale, False

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        end = time.monotonic() + self.wait
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                self.held = True
                return True
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        self.path.unlink()
                        continue
                except OSError:
                    continue
            if time.monotonic() >= end:
                return False
            time.sleep(0.05)

    def touch(self):
        """Keep a long holder alive: a tick that runs for minutes must not look stale."""
        try:
            os.utime(self.path)
        except OSError:
            pass

    def release(self):
        if self.held:
            self.held = False
            try:
                self.path.unlink()
            except OSError:
                pass

    def __enter__(self):
        if not self.acquire():
            raise LockError(f"the lock {self.path} was not taken in {self.wait:.0f} s")
        return self

    def __exit__(self, *exc):
        self.release()


def store_lock():
    return Lock(paths.config_root() / ".store.lock")


def farm_of(directory="."):
    """(name, path) of the farm containing `directory`: the main checkout's project name and real path."""
    directory = os.path.realpath(directory)
    if not os.path.isdir(directory):
        raise StoreError(f"no such folder: {directory}")
    return roles.project(directory), os.path.realpath(roles.main_checkout(directory))


def farm_file(name):
    return paths.config_root() / f"{name}.yaml"


def farm_files():
    """[(name, path)] of every farm file, sorted by name."""
    folder = paths.config_root()
    return sorted((p.stem, p) for p in folder.glob("*.yaml")) if folder.is_dir() else []


def load(name):
    """(comments, watches) of a farm's file; ([], []) when it does not exist. Raises watchfile.YamlError."""
    path = farm_file(name)
    if not path.exists():
        return [], []
    return watchfile.parse(path.read_text(encoding="utf-8"))


def save(name, comments, watches):
    path = farm_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".farm.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(watchfile.dump(comments, watches))
    os.replace(tmp, path)


def find_watch(watch_id, farm=None):
    """(farm name, watch id) of the one farm file that holds `watch_id`; `farm` narrows it to one name."""
    hits = [name for name, _ in farm_files() if (farm in (None, name))
            and any(w.get("id") == watch_id for w in load(name)[1])]
    if not hits:
        raise StoreError(f"no watch {watch_id!r}" + (f" in farm {farm}" if farm else ""))
    if len(hits) > 1:
        raise StoreError(f"watch {watch_id!r} is in several farms ({', '.join(hits)}): add --farm DIR")
    return hits[0]


def actor(by=None):
    if by or os.environ.get("LOOKOUT_BY"):
        return by or os.environ["LOOKOUT_BY"]
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = "user"
    return f"{user}@{socket.gethostname()}"


def changes_path():
    return paths.config_root() / "changes.jsonl"


def log_change(farm, watch, op, changes, by, now=None, **extra):
    line = {"at": (now or paths.now()).isoformat(), "by": actor(by), "farm": farm, "watch": watch, "op": op,
            "changes": changes}
    line.update(extra)
    paths.append_log(line, changes_path())


def read_changes(farm=None, watch=None, since=None):
    """The change lines, optionally of one farm and watch and from the ISO date or time `since` on."""
    return [c for c in paths.read_log(changes_path())
            if (not farm or c.get("farm") == farm) and (not watch or c.get("watch") == watch)
            and (not since or str(c.get("at", "")) >= since)]


def program_exists(check, farm_path):
    """Does the check's program exist: a path (relative to the farm, the check's cwd) or a command on PATH?"""
    try:
        words = runner.argv(check)
    except ValueError as exc:
        raise StoreError(f"check: {exc}") from exc
    if not words:
        raise StoreError("check is empty")
    program = words[0]
    if "/" in program or os.sep in program:
        target = Path(program)
        return (target if target.is_absolute() else Path(farm_path) / target).is_file()
    return shutil.which(program) is not None


def _text(key, value):
    value = " ".join(str(value).split())
    if not value:
        raise StoreError(f"{key} is empty")
    return value


def _number(key, value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise StoreError(f"{key} {value!r} is not a number") from exc
    if not low <= number <= high:
        raise StoreError(f"{key} {value} is out of range {low}-{high}")
    return number


def normalise(key, value, farm_path):
    """The stored form of one key's value, or a StoreError. An empty optional value is None (removes the key)."""
    if key in OPTIONAL and str(value).strip() == "":
        return None
    if key == "cron":
        try:
            watchfile.parse_cron(value)
        except ValueError as exc:
            raise StoreError(str(exc)) from exc
        return " ".join(str(value).split())
    if key == "check":
        if not program_exists(value, farm_path):
            raise StoreError(f"the check's program does not exist: {runner.argv(value)[0]}")
        return str(value).strip()
    if key == "timeout":
        return int(_number(key, value, 1, runner.MAX_TIMEOUT))
    if key == "budget":
        return f"{_number(key, value, 0.0001, 0.50):g}"
    if key == "active":
        if str(value).lower() not in ("true", "false"):
            raise StoreError("active is true or false")
        return str(value).lower() == "true"
    if key == "notify":
        names = [n.strip() for n in str(value).split(",") if n.strip()]
        if names not in (["default"], ["none"]) and (not names or not set(names) <= set(BACKENDS)):
            raise StoreError("notify is default, none or a comma list of desktop,telegram")
        return ",".join(names)
    return _text(key, value)


def _guard_farm(watches, farm_path):
    for watch in watches:
        if watch.get("farm") and os.path.realpath(watch["farm"]) != farm_path:
            raise StoreError(f"this file already holds watches of {watch['farm']}: two farms with one name")


def add(name, farm_path, watch_id, fields, by=None, now=None):
    """Add a watch: `fields` has title, cron, check and the optional keys. Returns the record."""
    now = now or paths.now()
    if not ID_RE.match(watch_id):
        raise StoreError(f"watch id {watch_id!r} is not kebab case")
    record = {"id": watch_id, "active": True, "farm": farm_path, "created": now.date().isoformat(), "by": actor(by)}
    for key in ("title", "cron", "check"):
        if not fields.get(key):
            raise StoreError(f"add needs --{key}")
    for key, value in fields.items():
        if value is not None and key in ("title", "cron", "check") + OPTIONAL:
            value = normalise(key, value, farm_path)
            if value is not None:
                record[key] = value
    with store_lock():
        comments, watches = load(name)
        _guard_farm(watches, farm_path)
        if any(w.get("id") == watch_id for w in watches):
            raise StoreError(f"watch {watch_id!r} exists already in farm {name}")
        log_change(name, watch_id, "add", {k: [None, v] for k, v in sorted(record.items())}, by, now)
        save(name, comments, watches + [record])
    return record


def _edit(name, watch_id, op, edit, by, now, **extra):
    """Under the lock: apply `edit(record) -> changes` to one record, log the change line, then save."""
    now = now or paths.now()
    with store_lock():
        comments, watches = load(name)
        record = next((w for w in watches if w.get("id") == watch_id), None)
        if record is None:
            raise StoreError(f"no watch {watch_id!r} in farm {name}")
        changes = edit(record)
        if changes:
            log_change(name, watch_id, op, changes, by, now, **extra)
            save(name, comments, watches)
    return changes


def set_keys(name, watch_id, fields, by=None, now=None):
    """Change keys of a watch; returns {key: [old, new]} (empty when nothing changed)."""
    unknown = sorted(set(fields) - set(EDITABLE))
    if unknown:
        raise StoreError(f"cannot set {', '.join(unknown)} (editable: {', '.join(EDITABLE)})")
    if not fields:
        raise StoreError("set needs at least one --<key> <value>")

    def edit(record):
        changes = {}
        for key, value in fields.items():
            new = normalise(key, value, record.get("farm") or ".")
            if new is None and key in ("title", "cron", "check"):
                raise StoreError(f"{key} cannot be empty")
            old = record.get(key)
            if new == old:
                continue
            changes[key] = [old, new]
            if new is None:
                record.pop(key, None)
            else:
                record[key] = new
        return changes

    return _edit(name, watch_id, "set", edit, by, now)


def end(name, watch_id, by=None, now=None, reason=""):
    """End a watch (`active: false`, kept as history); returns the changes (empty when it had ended)."""
    def edit(record):
        if record.get("active", True) is False:
            return {}
        record["active"] = False
        return {"active": [True, False]}

    return _edit(name, watch_id, "end", edit, by, now, **({"reason": reason} if reason else {}))


def update_run_keys(name, watch_id, keys, end_reason=None, now=None):
    """The tick's write (D10): only the run keys, no change line; `end_reason` also ends the watch (logged by
    `lookout tick`). A watch removed or changed meanwhile is simply found again by id."""
    now = now or paths.now()
    with store_lock():
        comments, watches = load(name)
        record = next((w for w in watches if w.get("id") == watch_id), None)
        if record is None:
            return
        record.update({k: v for k, v in keys.items() if k in RUN_KEYS})
        if end_reason and record.get("active", True) is not False:
            record["active"] = False
            log_change(name, watch_id, "end", {"active": [True, False]}, TICK_BY, now, reason=end_reason)
        save(name, comments, watches)

