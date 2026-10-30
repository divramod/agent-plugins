"""A silenced round's output (hal2 plan 0349 D6, silence.py): one table line per train that changed or stands.

Split from tollman.py (plan 0480 D3, small-files); `tollman.silent_lines` calls `of`.
"""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import minute
import silence
import train_state

STATE = {"formed": "formed", "started": "landing", "red": "red", "order": "fixing", "fixed": "fixing",
         "pause": "paused by a smuggle", "resumed": "landing", "retry": "lands again", "landed": "in the barn", "cleared": "broken up"}


def of(main: str, r: dict, since: str, wiring) -> list[str]:
    """A silenced round (silence.py): one table line per train that changed since `since` (UTC, train_state.utc) or
    stands now, `joined` the fields that rode it (the yard as `yard`); none: a line saying so."""
    if r.get("problem"):
        return silence.round_lines(r, wiring)
    told = [a["text"] for a in r.get("done", []) if a["duty"] == minute.KIND and a["do"] == "record"]  # the watch's events
    rows = train_state.lines(main)
    names = list(dict.fromkeys(e["train"] for e in rows if e.get("train") and e.get("at", "") >= since))
    stands = train_state.standing(rows)
    if stands and stands["train"] not in names:
        names.append(stands["train"])
    out = []
    for name in names:
        mine = [e for e in rows if e.get("train") == name]
        formed = next((e for e in mine if e["kind"] == "formed"), {})
        state = next((STATE[e["kind"]] for e in reversed(mine) if e["kind"] in STATE), "formed")
        joined = [c["field"] for c in formed.get("cars", [])] + (["yard"] if any(e["kind"] == "yard" for e in mine) else [])
        out.append(silence.line(wiring.role, f"train {name}: {state}", joined))
    return told + (out or [silence.line(wiring.role, "no train")])
