"""The state file of a farm's timers that run outside the farmer's tick (hal2 plan 0695 step 14, D31): written by
`actions/prune/scripts/prune_timer.py`, read by `due.py check`, so a dead timer is seen. Defined once here (record
cross-unit-formats-have-a-schema).

  prune-timer.json in the farmer's state folder:
  {"schema": 1, "label": "<launchd label>",
   "round": {"id": <int, the start second>, "pid": <int>, "started": <epoch s>, "ended": <epoch s | null>,
             "rc": <int | null>, "failed": [{"field": "05", "action": "trim", "reason": "<the refusing proof and path>"}]},
   "seen": {"ticked": <epoch s>, "fail_open": <bool, a red incident is open: alarmed once>, "long": <round id alarmed>}}

`line(folder, now)` is the sentence `due.py check` prints. Stdlib only; a missing or unreadable file is None.
"""

import json
import os
import time
from pathlib import Path

SCHEMA = 1
FILE = "prune-timer.json"
DEAD_AFTER = 45 * 60  # no tick for 45 min (the timer ticks every 5) is a dead timer


def load(folder: Path) -> dict | None:
    try:
        state = json.loads((Path(folder) / FILE).read_text())
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("schema") == SCHEMA else None


def save(folder: Path, state: dict) -> None:
    """Atomic: a reader never sees half a file."""
    state["schema"] = SCHEMA
    path = Path(folder) / FILE
    tmp = path.with_name(f".{FILE}.{os.getpid()}")
    tmp.write_text(json.dumps(state, indent=1) + "\n")
    os.replace(tmp, path)


def minutes(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60} h {m % 60} min" if m >= 120 else f"{m} min"


def line(folder: Path, now: float | None = None) -> str:
    """One sentence: the timer, its last tick and its last round; says so when nothing ticked for a long time."""
    now = time.time() if now is None else now
    state = load(folder)
    if state is None:
        return "timer prune: no state yet (not installed, or never ticked)"
    label = state.get("label", "prune")
    ticked = (state.get("seen") or {}).get("ticked")
    r = state.get("round") or {}
    parts = [f"timer {label}"]
    if ticked is None or now - ticked > DEAD_AFTER:
        parts.append("DEAD: " + (f"last tick {minutes(now - ticked)} ago" if ticked else "never ticked"))
    else:
        parts.append(f"last tick {minutes(now - ticked)} ago")
    if r.get("ended") is None and r.get("started") is not None:
        parts.append(f"round running for {minutes(now - r['started'])}")
    elif r.get("ended"):
        parts.append(f"last round {'ok' if r.get('rc') == 0 else 'RED (rc ' + str(r.get('rc')) + ')'}, "
                     f"{minutes(now - r['ended'])} ago")
        if r.get("rc") != 0 and r.get("failed"):
            parts.append("failed: " + "; ".join(f"{x['field']} {x['action']}: {x['reason']}" for x in r["failed"]))
    return ", ".join(parts)
