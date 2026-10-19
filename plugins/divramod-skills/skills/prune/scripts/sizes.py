"""Field sizes by a budgeted `os.scandir` walk (hal2 plan 0377, D9, D18).

`du` over every field took over 5 minutes under load and cannot stop where it is, so a field is walked here: iterative
(no recursion limit), symlinks not followed, a hard link counted once, allocated bytes where the system tells
(`st_blocks`), else the apparent size. Each field has its own time budget; over it the walk stops and returns what it
counted as a lower bound (`lower_bound: true`, shown "≥ 12.3 GB"). Fields are walked in parallel, at most half the cores.

The result is cached in the farm's prune state folder by the field's HEAD and a stamp of its root's mtime (the root's
and its entries'), and for CACHE_TTL at most: a build folder that grows deep inside still ages out. A lower bound is
never cached, so the next run measures again.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import store

BUDGET_S = 20.0  # per field
CACHE_TTL = 6 * 3600
CACHE_FILE = "sizes.json"
CHECK_EVERY = 500  # entries between two looks at the clock


def allocated(st: os.stat_result) -> int:
    blocks = getattr(st, "st_blocks", None)
    return blocks * 512 if blocks is not None else st.st_size


def walk(path: str | Path, budget: float = BUDGET_S, clock=time.monotonic) -> dict:
    """{bytes, files, lower_bound} of the tree under `path`; unreadable entries are skipped."""
    start, total, files, seen, seen_entries = clock(), 0, 0, set(), 0
    stack = [str(path)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for entry in it:
                    seen_entries += 1
                    if seen_entries % CHECK_EVERY == 0 and clock() - start > budget:
                        return {"bytes": total, "files": files, "lower_bound": True}
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if st.st_nlink > 1:
                        key = (st.st_dev, st.st_ino)
                        if key in seen:
                            continue
                        seen.add(key)
                    total += allocated(st)
                    files += 1
        except OSError:
            pass
        if clock() - start > budget and stack:
            return {"bytes": total, "files": files, "lower_bound": True}
    return {"bytes": total, "files": files, "lower_bound": False}


def stamp(path: str | Path) -> str:
    """The root's mtime and its newest entry's (one level, no walk): changes when something is added or removed at
    the top, which a build or a checkout does."""
    newest = 0
    try:
        newest = os.stat(path).st_mtime_ns
        with os.scandir(path) as it:
            for e in it:
                try:
                    newest = max(newest, e.stat(follow_symlinks=False).st_mtime_ns)
                except OSError:
                    continue
    except OSError:
        pass
    return str(newest)


def _hit(field: dict, cache: dict, now: float) -> dict | None:
    """The cached size of a field `{path, head}` when its HEAD, stamp and age match, else None."""
    hit = cache.get(field["path"])
    if hit and hit.get("head") == field.get("head", "") and hit.get("stamp") == stamp(field["path"]) \
            and now - hit.get("at", 0) < CACHE_TTL:
        return dict(hit["size"])
    return None


def measure_one(field: dict, cache: dict, budget: float, now: float, clock=time.monotonic) -> dict:
    """The size of one field `{path, head}`: from the cache when its HEAD, stamp and age match, else a walk."""
    path, head, mark = field["path"], field.get("head", ""), stamp(field["path"])
    hit = cache.get(path)
    if hit and hit.get("head") == head and hit.get("stamp") == mark and now - hit.get("at", 0) < CACHE_TTL:
        return {**hit["size"], "cached": True, "_entry": None}
    size = {**walk(path, budget, clock), "cached": False}
    entry = None if size["lower_bound"] else {"head": head, "stamp": mark, "at": now, "size": {
        k: size[k] for k in ("bytes", "files", "lower_bound")}}
    return {**size, "_entry": entry}


def workers() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


def measure_all(main: str | Path, fields: list[dict], budget: float = BUDGET_S, now: float | None = None,
                clock=time.monotonic, pool: int | None = None, cached_only: bool = False) -> dict[str, dict | None]:
    """{slot: {bytes, files, lower_bound, cached}} for fields `{slot, path, head}`; the cache is read once and written
    once, holding only the fields given. `cached_only`: cache hits only, a miss is None (unknown), no walk, no write."""
    now = time.time() if now is None else now
    cache_file = store.state_dir(main) / CACHE_FILE
    cache = store.read_json(cache_file, {})
    if cached_only:
        hits = {f["slot"]: _hit(f, cache, now) for f in fields}
        return {slot: hit and {**hit, "cached": True} for slot, hit in hits.items()}
    with ThreadPoolExecutor(max_workers=pool or workers()) as ex:
        done = list(ex.map(lambda f: measure_one(f, cache, budget, now, clock), fields))
    fresh = {}
    for f, size in zip(fields, done):
        entry = size.pop("_entry")
        if entry:
            fresh[f["path"]] = entry
        elif size["cached"]:
            fresh[f["path"]] = cache[f["path"]]
    store.write_json(cache_file, fresh)
    return {f["slot"]: size for f, size in zip(fields, done)}


def human(size: dict | int | None) -> str:
    """"12.3 GB", "≥ 12.3 GB" for a lower bound, "unknown" for none."""
    if size is None:
        return "unknown"
    n, bound = (size, False) if isinstance(size, int) else (size["bytes"], size.get("lower_bound", False))
    value, unit = float(n), "B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            break
        value /= 1000
    text = f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
    return f"≥ {text}" if bound else text
