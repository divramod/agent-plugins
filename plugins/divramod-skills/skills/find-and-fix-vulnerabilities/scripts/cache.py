"""A tiny JSON cache for step 2's feeds (KEV, OSV): a file under the hal2 cache root, a maximum age, offline reads only."""
import json
import os
import time
import urllib.request
from pathlib import Path

import paths

MAX_AGE = 12 * 3600


def cache_dir() -> Path:
    """paths.cache_root(): $HAL2_VULNS_CACHE, else the XDG cache folder."""
    return paths.cache_root()


def http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "hal2-find-and-fix-vulnerabilities"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (https URLs fixed in code)
        return resp.read().decode("utf-8")


def load(url: str, path: Path, offline: bool = False, fetch=http_get, max_age: int = MAX_AGE, now=None):
    """The JSON of `url`: the cache file when fresh, else fetched and cached; a failed fetch falls back to a stale
    cache. Offline reads the cache only (any age). Raises FileNotFoundError offline without cache, OSError/ValueError
    when fetching fails without cache."""
    now = time.time() if now is None else now
    have = path.is_file()
    if have and (offline or now - path.stat().st_mtime <= max_age):
        return json.loads(path.read_text())
    if offline:
        raise FileNotFoundError(f"{path}: no cache and --offline")
    try:
        text = fetch(url)
        data = json.loads(text)
    except (OSError, ValueError):
        if have:
            return json.loads(path.read_text())
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
    return data
