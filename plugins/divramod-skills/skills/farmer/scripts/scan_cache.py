"""The round's one scan (hal2 plan 0333 step 7): `duty:mtm` (the tollman's `boss.handler`) takes a
`mtm_scan.snapshot` and writes it to the role's `last-scan.json`; the round's summary and the orphans check used to
take a second one (63 of the tollman's 168 tick minutes on 2026-10-14). `scan` reads that file back when it is
fresh and takes a new snapshot only when it is missing, unreadable or stale.

Fresh: at most FRESH_S seconds old (10 min, plan 0480 step 02.02: the summary needs no scan of its own when the
last round's is that young) or written during this round (its mtime at or after `since`, the round's start; a long
round's own scan stays fresh). The file is the carrier because the duty's planner and the summary share no object
(`tick.context` is local to `plan_round`).
"""

import json
import time

import mtm_scan

FRESH_S = 600  # a scan this young serves the summary, this round's or an earlier one's


def fresh(main: str, role: str, since: float | None = None, now: float | None = None) -> dict | None:
    """The role's `last-scan.json` when it is fresh, else None (missing, unreadable, not a scan, or stale)."""
    f = mtm_scan.state_dir(main, role) / "last-scan.json"
    try:
        written = f.stat().st_mtime
        snap = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(snap, dict) or "findings" not in snap:
        return None
    ok = (since is not None and written >= since) or (now or time.time()) - written <= FRESH_S
    return snap if ok else None


def scan(top: str, role: str, since: float | None = None, snapshot=None) -> dict:
    """The round's scan: the fresh `last-scan.json`, else a new `snapshot(top, 24, fetch=False, role=role)`
    (the round's merge-from-main fetched origin already)."""
    snap = fresh(mtm_scan.main_checkout(top), role, since)
    if snap is not None:
        return snap
    return (snapshot or mtm_scan.snapshot)(top, 24, fetch=False, role=role)
