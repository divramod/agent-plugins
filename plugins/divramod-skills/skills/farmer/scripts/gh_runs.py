"""GitHub Actions runs read once per round (plan 0011): mtm_ci (the boss's snapshot, trains, the orphans task) and
ci_scan read the same land runs; each `gh run list` and each run's `gh run view --json jobs` now costs one call.

Inside `with gh_runs.round(main):` (tick.run opens one per tick) a list or a run's jobs is fetched once and shared;
a completed run's jobs never change, so they are also kept on disk by run id (`cache/run-jobs/<id>.json` in the
farmer's state folder, files older than KEEP removed) and read back in later rounds; a running run's jobs are fetched
again next round. Uncached runs are fetched in parallel (POOL threads: gh is I/O bound). Outside a round nothing is
memoized and nothing is written: every call fetches, as before.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

POOL = 6
KEEP = 7 * 24 * 3600

_round: dict | None = None  # {"cache": Path | None, "lists": {}, "jobs": {}, "stats": {...}}


@contextmanager
def round(cache: Path | None):  # noqa: A001  (a farmer round, not the builtin)
    """Memoize lists and jobs until the block ends; `cache` is the folder for completed runs' jobs (None: no disk).
    Yields the round's stats: gh calls made (`list`, `view`) and runs whose jobs came from the disk (`cached`)."""
    global _round
    outer, stats = _round, {"list": 0, "view": 0, "cached": 0}
    if cache is not None:
        prune(cache)
    _round = {"cache": cache, "lists": {}, "jobs": {}, "stats": stats}
    try:
        yield stats
    finally:
        _round = outer


def cache_dir(state: Path) -> Path | None:
    """`cache/run-jobs` in the farmer's state folder; None when that folder does not exist (nothing is created)."""
    return state / "cache" / "run-jobs" if state.is_dir() else None


def prune(cache: Path, now: float | None = None) -> None:
    now = now or time.time()
    for f in cache.glob("*.json") if cache.is_dir() else []:
        try:
            if now - f.stat().st_mtime > KEEP:
                f.unlink()
        except OSError:
            pass


def listed(run_json, args: list[str], cwd: str):
    """`run_json(args, cwd)` for a `gh run list`, once per round."""
    if _round is None:
        return run_json(args, cwd)
    key = (tuple(args), cwd)
    if key not in _round["lists"]:
        _round["stats"]["list"] += 1
        _round["lists"][key] = run_json(args, cwd)
    return _round["lists"][key]


def _cache() -> Path | None:
    return _round["cache"] if _round is not None else None


def _disk(rid) -> list[dict] | None:
    cache = _cache()
    if cache is None:
        return None
    try:
        return json.loads((cache / f"{rid}.json").read_text())
    except (OSError, ValueError):
        return None


def _keep(rid, jobs: list[dict]) -> None:
    cache = _cache()
    if cache is None or not jobs:
        return
    try:
        cache.mkdir(parents=True, exist_ok=True)
        tmp = cache / f".{rid}.json.tmp"
        tmp.write_text(json.dumps(jobs))
        tmp.replace(cache / f"{rid}.json")
    except OSError:
        pass


def jobs(ids, completed, fetch) -> dict:
    """{run id: its jobs} for `ids`; `completed` names the runs that finished (their jobs are kept on disk),
    `fetch(run id)` gets one run's jobs (`gh run view <id> --json jobs`). Uncached runs are fetched in parallel."""
    ids = list(dict.fromkeys(ids))
    memo = _round["jobs"] if _round is not None else {}
    out, todo = {}, []
    for rid in ids:
        if rid in memo:
            out[rid] = memo[rid]
        elif _round is not None and rid in completed and (hit := _disk(rid)) is not None:
            out[rid] = memo[rid] = hit
            _round["stats"]["cached"] += 1
        else:
            todo.append(rid)
    if todo:
        with ThreadPoolExecutor(min(POOL, len(todo))) as pool:
            fetched = list(pool.map(fetch, todo))
        for rid, got in zip(todo, fetched):
            got = got or []
            out[rid] = memo[rid] = got
            if _round is not None:
                _round["stats"]["view"] += 1
                if rid in completed:
                    _keep(rid, got)
    return out


def view_jobs(run_json, cwd: str):
    """The fetch for `jobs`: one run's jobs through `run_json` (gh run view <id> --json jobs)."""
    return lambda rid: (run_json(["gh", "run", "view", str(rid), "--json", "jobs"], cwd) or {}).get("jobs", [])
