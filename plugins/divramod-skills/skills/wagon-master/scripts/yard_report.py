"""What the wagon master says about the yard (hal2 plan 0294 step 8, D15): the frame's actions and the dry run's
lines; yard.py reads, engine.py carries and settles.

  left_actions     when a train forms: the files the yard keeps (yard.sort's `left`), or why the whole yard is
                   skipped, told to the farmer in one line. A `send` to the farmer's field with a `key` per set of
                   paths and reasons, so it goes out once, not every round; board.sync copies it to the message
                   board as a `message` to the farmer's field
  settled_actions  after a landing: the carried files yard.settle kept (changed meanwhile) and a yard that was not
                   fast-forwarded, told to the farmer once per train
  lines            `wagon_master.py train --dry-run`: placed and left, one line each

A fault here never stops a round: the yard never holds a train.
"""

import datetime as dt
import hashlib
import subprocess

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import train_state
import yard
from tick import act

SHOWN = 8  # paths named in one message; the dry run lists all
DAY = 24 * 3600
ROLE = "wagon-master (yard)"
TEXT = {
    "left": ROLE + ": {n} of the yard's uncommitted files stay there, the train does not bring them in: {files}. "
                   "Bring them in from a field, gitignore them or leave them; `wagon_master.py train --dry-run` "
                   "lists them all.",
    "skipped": ROLE + ": the yard's uncommitted work is not brought in: {why}. Nothing there was changed.",
    "kept": ROLE + ": train {train} is in the barn, but {what}. Nothing there was forced: look at the yard, then "
                   "`git pull --ff-only` there.",
}


def seen(main: str, base: str, default: str, cars: list[dict], rows: list[dict]) -> dict:
    """yard.look with the train state's past; a fault is a skipped yard."""
    try:
        return yard.look(main, base, default, cars, train_state.yard_past(rows))
    except (OSError, subprocess.SubprocessError) as e:
        return {"skipped": f"the yard could not be read: {e}", "placed": [], "left": []}


def named(items: list[dict]) -> str:
    more = f"; {len(items) - SHOWN} more" if len(items) > SHOWN else ""
    return "; ".join(f"{x['path']} ({x['why']})" for x in items[:SHOWN]) + more


def to_farmer(main: str, kind: str, key: str, text: str, panes: dict) -> dict:
    farmer = mtm_scan.roles.slot_name(main)
    return act("trains", kind, "send", farmer, pane=panes.get(farmer), key=key, text=text)


def left_actions(main: str, d: dict, default: str, rows: list[dict], panes: dict) -> list[dict]:
    """For the train `d` (trains.draft) that forms now; no cars, a clean yard or nothing left: nothing."""
    if not d["cars"]:
        return []
    s = seen(main, d["base"], default, d["cars"], rows)
    if not s["skipped"] and not s["left"]:
        return []
    text = (TEXT["skipped"].format(why=s["skipped"]) if s["skipped"]
            else TEXT["left"].format(n=len(s["left"]), files=named(s["left"])))
    what = repr((s["skipped"], sorted((x["path"], x["why"]) for x in s["left"])))
    return [to_farmer(main, "yard-left", "yard-left:" + hashlib.sha1(what.encode()).hexdigest()[:12], text, panes)]


def settled_actions(main: str, rows: list[dict], panes: dict, now: dt.datetime | None = None) -> list[dict]:
    """For the last landed train, within a day of it: what yard.settle left undone."""
    last = next((e for e in reversed(rows) if e["kind"] == "landed"), None)
    home = (last or {}).get("yard") or {}
    if not home or (home.get("pulled") and not home.get("kept")):
        return []
    at = dt.datetime.fromisoformat(last["at"].replace("Z", "+00:00"))
    if ((now or dt.datetime.now(dt.timezone.utc)) - at).total_seconds() > DAY:
        return []
    kept = home.get("kept") or []
    parts = [f"{len(kept)} of the files it carried from the yard stay there as they are ({named(kept)})"] * bool(kept)
    parts += [] if home.get("pulled") else [f"the yard was not fast-forwarded ({home.get('why') or 'no reason given'})"]
    text = TEXT["kept"].format(train=last.get("train"), what=" and ".join(parts))
    return [to_farmer(main, "yard-kept", f"yard-kept:{last.get('train')}", text, panes)]


def lines(s: dict) -> list[str]:
    """The dry run's lines for what `seen` found."""
    if s["skipped"]:
        return [f"yard: skipped: {s['skipped']}"]
    return ([f"yard: placed: {e['path']}" + (" (deleted)" if e["deleted"] else "") for e in s["placed"]]
            + [f"yard: left: {x['path']}: {x['why']}" for x in s["left"]])
