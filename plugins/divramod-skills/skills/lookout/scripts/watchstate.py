"""A watch's `state.json` (plan 0311 design.md, Store and Check contract): dedupe, pending events, alert counters.

Keys: `delivered` {event id: time, kept 30 days}, `pending` [{event, step, attempts, find?}], `failures` (broken
runs in a row) and `broken_since`, `unreachable_since` and `cause` (exit 75), `alerted` {cause: time}, `since`
(the start of the last run that ended 0, 10 or 11, in UTC: the check's `LOOKOUT_SINCE`, D17). Only the tick
writes it. Stdlib only.
"""

import datetime as dt
import json
import os
import tempfile
from pathlib import Path

KEEP_DELIVERED = dt.timedelta(days=30)
BROKEN_ALERT = 3
UNREACHABLE_ALERT = dt.timedelta(hours=6)
ALERT_AT_ONCE = ("auth", "botcheck")


def empty():
    return {"delivered": {}, "pending": [], "failures": 0, "unreachable_since": None, "cause": None,
            "alerted": {}, "since": "", "broken_since": None}


def load(watch_dir):
    """The state of the watch whose folder is `watch_dir`; a fresh one when missing or broken."""
    state = empty()
    try:
        data = json.loads((Path(watch_dir) / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if isinstance(data, dict):
        state.update({k: v for k, v in data.items() if k in state})
    return state


def save(watch_dir, state):
    """Write state.json atomically (temp file and replace)."""
    folder = Path(watch_dir)
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".state.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, folder / "state.json")


def utc(when):
    """ISO 8601 in UTC with its offset, to the second (`2026-10-14T09:00:00+00:00`): `since` and `LOOKOUT_SINCE`
    (D17)."""
    return when.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def _parse(at):
    try:
        return dt.datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return None


def prune(state, now):
    """Drop delivered ids older than 30 days."""
    keep = {}
    for event_id, at in state["delivered"].items():
        when = _parse(at)
        if when is None or now - when <= KEEP_DELIVERED:
            keep[event_id] = at
    state["delivered"] = keep


def new_events(state, events):
    """The events not yet delivered nor pending, each id once, in the check's order."""
    seen = set(state["delivered"]) | {p["event"]["id"] for p in state["pending"]}
    fresh = []
    for event in events:
        if event["id"] not in seen:
            seen.add(event["id"])
            fresh.append(event)
    return fresh


def deliver(state, event_id, now):
    """Mark an event delivered (its find is done, or the judge said ignore) and drop it from pending."""
    state["delivered"][event_id] = now.isoformat()
    state["pending"] = [p for p in state["pending"] if p["event"]["id"] != event_id]


def set_pending(state, event, step, attempts, find=None):
    """Keep an event pending at `step` with its attempts so far: `judge` (the judge failed), `find` (judged, its
    find not yet written; `find` holds it, so a retry never judges twice), or a later find step (step 4)."""
    state["pending"] = [p for p in state["pending"] if p["event"]["id"] != event["id"]]
    entry = {"event": event, "step": step, "attempts": attempts}
    if find is not None:
        entry["find"] = find
    state["pending"].append(entry)


def _alert(state, cause, since, title, now):
    if cause in state["alerted"]:
        return None
    state["alerted"][cause] = now.isoformat()
    return {"cause": cause, "since": since,
            "message": f"Watch {title} not checkable since {since}: {cause}"}


def account(state, kind, cause, started, title, now):
    """Count one run's outcome; returns the alert to raise ({cause, since, message}) or None.

    `kind` is quiet, found, settled, unreachable or broken. A clean run (quiet, found, settled) clears the counters
    and the alerts and moves `since` to the run's start. 3 broken in a row, or 75 for 6 h, alert once per cause;
    `auth` and `botcheck` alert on the first 75.
    """
    if kind in ("quiet", "found", "settled"):
        state.update(failures=0, broken_since=None, unreachable_since=None, cause=None, alerted={},
                     since=utc(started))
        return None
    if kind == "broken":
        state["failures"] += 1
        state["broken_since"] = state["broken_since"] or started.isoformat()
        if state["failures"] >= BROKEN_ALERT:
            return _alert(state, "broken", state["broken_since"], title, now)
        return None
    cause = cause or "unknown"
    if not state["unreachable_since"]:
        state["unreachable_since"] = started.isoformat()
    state["cause"] = cause
    since = _parse(state["unreachable_since"]) or started
    if cause in ALERT_AT_ONCE or now - since >= UNREACHABLE_ALERT:
        return _alert(state, cause, state["unreachable_since"], title, now)
    return None
