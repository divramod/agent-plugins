"""`tollman.py status` (hal2 plan 0294): is there a tollman here, as data and as text.

Split from tollman.py (plan 0480 D3, small-files); `tollman.status` calls `status` with its wiring.
"""

import datetime as dt
import json
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import due
import hold
import mtm_scan
import role_cli
import roles
import timer
import wake


def last_tick(state: Path) -> dt.datetime | None:
    """When the last round ran: the newest of the log's entries written by a tick and the run records."""
    at = [e["at"] for e in mtm_scan.entries(state / "log.jsonl") if e.get("by") == "tick"]
    runs = state / "runs.jsonl"
    at += [json.loads(line)["at"] for line in runs.read_text().splitlines()] if runs.exists() else []
    return max(map(dt.datetime.fromisoformat, at), default=None)


def status(repo: str, wiring: roles.Wiring, now: dt.datetime | None = None) -> dict:
    """The tollman of `repo`'s farm as data, from any checkout of it; a farm without the field has no state
    (nothing is created for it): no timer file, no last tick."""
    field, state = roles.slot_dir(repo, wiring.role), role_cli.state(repo, wiring)
    last = last_tick(state)
    age = int(((now or dt.datetime.now()) - last).total_seconds()) if last else None
    return {"role": wiring.role, "field": str(field), "field_exists": field.is_dir(),
            "timer": timer.status(due.repo_name(repo), state, wiring), "mode": role_cli.mode(repo, wiring),
            "last_tick": last.isoformat(timespec="seconds") if last else None, "last_tick_age_s": age,
            "pending": len(wake.read(mtm_scan.main_checkout(repo), wiring)["items"]),
            "held": hold.text(h) if (h := hold.of(mtm_scan.main_checkout(repo))) else None}


def show(s: dict) -> None:
    t = s["timer"]
    print(f"{s['field']}: {'exists' if s['field_exists'] else 'no field'}")
    print(f"timer {t.get('label', '-')}: {'loaded' if t.get('loaded') else 'not loaded'}, cron {t.get('cron', '-')}, "
          f"mode {s['mode']}")
    print(f"last tick: {s['last_tick'] or 'never'}"
          + (f" ({s['last_tick_age_s']} s ago)" if s["last_tick"] else "") + f"; {s['pending']} wake items")
    if s.get("held"):
        print(s["held"])
