"""The tollman's page (hal2 plan 0366 D9): the merge queue as the toll gate. Sections: the mode, the holder, the
trains, the ready wagons (hitched harvests), the waiters in order and the open land runs (`land/<field>` branches of
the collected runs; a train's `land/train-<plans>` is shown with its carrier, plan 0383). With nothing in the queue
and no land run: "The toll gate is empty." The raw queue comes from tollman_sources.py, the runs from
`state.collect`'s `runs`; a source that is unknown says so.
"""

import state_sources as src
import state_table
import tollman_sources as ts

EMPTY = "The toll gate is empty."


def mode_text(mode: dict | None) -> str:
    if not mode:
        return "Mode unknown."
    text = f"Mode: {mode.get('mode') or 'unknown'}"
    extra = [f"{k} {mode[k]}" for k in ("by", "at", "why") if mode.get(k)]
    return text + (f" ({', '.join(extra)})" if extra else "")


def note(t: dict) -> str:
    """The marks of a ticket in a few words, fixed order."""
    out = []
    red = src.red_of(t)
    if red:
        out.append(f"red: {state_table.red_phrase(red)}; holds the queue until it lands or is released")
    elif t.get("state") == "held":
        out.append("held" + (f": {t['hold'].get('reason') if isinstance(t['hold'], dict) else t['hold']}" if t.get("hold") else ""))
    if t.get("smuggle"):
        out.append("smuggle")
    if t.get("paused_by"):
        out.append("paused by a smuggle")
    if t.get("reserved"):
        out.append("reserved")
    if t.get("rides_with"):
        out.append(f"rides with {t['rides_with']}")
    if t.get("waits_for"):
        out.append(f"waits for {t['waits_for']}")
    return "; ".join(out)


def ticket_row(t: dict) -> list:
    return [t.get("position"), t.get("slot"), t.get("state") or "", note(t)]


def ready_row(t: dict) -> list:
    r = t["ready"] if isinstance(t.get("ready"), dict) else {}
    return [t.get("position"), t.get("slot"), r.get("at") or "", (r.get("head") or "")[:8], note(t)]


def train_row(t: dict) -> list:
    cars = [c.get("field") for c in t["train"].get("cars") or [] if isinstance(c, dict)]
    return [t.get("slot"), t["train"].get("carrier") or "", ", ".join(map(str, cars)) or "no cars", t["train"].get("at") or ""]


def queue_sections(tickets: list[dict]) -> list[dict]:
    tickets = sorted(tickets, key=lambda t: t.get("position") if isinstance(t.get("position"), int) else 10**9)
    holder = [t for t in tickets if t.get("holding")]
    trains = [t for t in tickets if isinstance(t.get("train"), dict)]
    rest = [t for t in tickets if not t.get("holding") and not isinstance(t.get("train"), dict)]
    ready = [t for t in rest if t.get("ready")]
    waiting = [t for t in rest if not t.get("ready")]
    cols = ["Place", "Field", "State", "Note"]
    return [
        {"heading": "Holder", "columns": cols, "rows": [ticket_row(t) for t in holder], "empty": "Nobody holds the gate."},
        {"heading": f"Trains ({len(trains)})", "columns": ["Field", "Carrier", "Cars", "Since"],
         "rows": [train_row(t) for t in trains], "empty": "No train."},
        {"heading": f"Ready wagons ({len(ready)})", "columns": ["Place", "Field", "Ready since", "Head", "Note"],
         "rows": [ready_row(t) for t in ready], "empty": "No wagon is hitched."},
        {"heading": f"Waiting in order ({len(waiting)})", "columns": cols, "rows": [ticket_row(t) for t in waiting],
         "empty": "Nobody else waits."},
    ]


def land_owner(branch: str, tickets: list[dict]) -> str:
    """Who a land run belongs to: `land/07` -> `07`; a train's `land/train-0383-0365` -> `train-0383-0365 (carrier)`,
    the carrier being the ticket that lands on it, else the bare train name."""
    name = branch[len("land/"):]
    carrier = next((t.get("slot") for t in tickets if (t.get("land_ref") or "").removeprefix("land/") == name), None)
    return f"{name} ({carrier})" if name.startswith("train-") and carrier else name


def land_runs(runs: list[dict] | None, tickets: list[dict] = ()) -> dict:
    if runs is None:
        return {"heading": "Open land runs", "empty": "Land runs unknown (gh is not available)."}
    mine = [r for r in runs if str(r.get("branch") or "").startswith("land/")]
    return {"heading": f"Open land runs ({len(mine)})", "columns": ["Field or train", "Workflow", "Status", "Run"],
            "rows": [[land_owner(r["branch"], tickets), r.get("workflow"), r.get("status"), r.get("url")] for r in mine],
            "empty": "No land run is open."}


def view(data: dict, ctx: dict) -> tuple[str, list[dict]]:
    import views  # late: views registers this module
    raw = ts.raw_queue(data["repo"])
    mode = (raw or {}).get("mode") or data.get("mode")
    runs = land_runs(data.get("runs"), (raw or {}).get("queue") or [])
    sections = [{"heading": "Mode", "text": mode_text(mode)}]
    if raw is None:
        sections.append({"heading": "Merge queue", "empty": "The queue is unknown (hal2-cli-git is not available)."})
    elif not raw["queue"] and data.get("runs") is not None and not runs["rows"]:
        sections.append({"heading": "Merge queue", "empty": EMPTY})
        return views.title_of(ctx), sections
    else:
        sections += queue_sections(raw["queue"])
    return views.title_of(ctx), sections + [runs]
