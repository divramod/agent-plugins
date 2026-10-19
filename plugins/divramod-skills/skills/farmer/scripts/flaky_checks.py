"""The farmer's flaky candidates from `hal2-cli-git worktree checks --json` (hal2 plan 0289 step 3, D20 (5)).

Where the installed CLI knows `worktree checks`, its farm-wide `flaky` list (`{test, count, fields, last}`, the
reds of the last seven days) is the source of `mtm_scan`'s `flaky-candidate`; where it does not (an older CLI, none
on PATH, unreadable output) `tests()` returns None and `mtm_scan` keeps counting failing tests in the landings
itself. The probe is the call: one per process and checkout, cached like the other probes (`reset()` in tests).
"""

_cache: dict[str, dict | None] = {}


def reset() -> None:
    _cache.clear()


def tests(run_json, main: str) -> dict | None:
    """`{test: {"test", "failures", "slots"}}` (the shape of `mtm_scan.landings_summary`'s tests), or None when
    the CLI does not know `worktree checks` (no JSON object with a `flaky` list)."""
    if main not in _cache:
        raw = run_json(["hal2-cli-git", "worktree", "checks", "--json"], main)
        _cache[main] = raw if isinstance(raw, dict) and isinstance(raw.get("flaky"), list) else None
    raw = _cache[main]
    if raw is None:
        return None
    out: dict[str, dict] = {}
    for t in raw["flaky"]:
        if isinstance(t, dict) and isinstance(t.get("test"), str):
            out[t["test"]] = {"test": t["test"], "failures": int(t.get("count") or 0),
                              "slots": [str(f) for f in t.get("fields") or []]}
    return out
