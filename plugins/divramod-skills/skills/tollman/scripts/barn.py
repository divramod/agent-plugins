"""After the barn (hal2 plan 0360 step 7, D8): the fields of the last landed train, on the rounds after it.

The foreman of a car restocks, finishes its plan, mucks out and ends its turn ("in the barn", trains.TEXT); it does
not clear itself. The prune duty (prune.py) then looks at each car of the newest `landed` line of train.jsonl, on
/prune's facts (names-ok: slot, path, HEAD, the proof's refusal `why`, the field's live `sessions`; hal2 plan 0377 step 7, D12):
- a field 00-09 that /prune's proof finds free and that is mucked out (prune's `clean` ran for this HEAD: its key in
  the log, no exit) has its resting session cleared once: `hal2-cli-agents clear-and-continue --pane <pane>
  --without-plan --prompt /merge-from-main --detach`, key `barn-clear:<slot>:<HEAD>`;
- a field 10-99 is removed by /prune's run (stopped by signal, removed through the proof): its plan orders the
  last train's cars first, so a car is removed right after the barn (prune.py starts the run for it);
- a car whose field still holds work 24 hours after the landing: one wake, `barn-stuck:<slot>:<HEAD>`, never a forced
  removal.
"""

import datetime as dt
import re
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import train_state
from tick import act

NUMBERED = re.compile(r"\d\d")  # a field 00-99 (a local copy: the tollman never imports /prune, plan 0377 D11)

STUCK_AFTER = 24 * 3600
ONCE = 30 * 24 * 3600
CLEAR = ["hal2-cli-agents", "clear-and-continue", "--without-plan", "--prompt", "/merge-from-main", "--detach"]


def last_landed(main: str) -> dict | None:
    """The newest `landed` line: its `cars` the fields that rode (the yard has no field)."""
    return next((e for e in reversed(train_state.lines(main)) if e.get("kind") == "landed"), None)


def cars(landed: dict | None) -> list[str]:
    return [c for c in (landed or {}).get("cars", []) if NUMBERED.fullmatch(str(c))]


def cleaned(log: list[dict], slot: str, head: str) -> bool:
    """Did prune's `clean` run for this HEAD (logged by the tick, without an exit)?"""
    key = f"prune:clean:{slot}:{head}"
    return any(e.get("key") == key and "(exit" not in str(e.get("note", "")) for e in log)


def age(landed: dict, now: dt.datetime) -> float:
    at = dt.datetime.fromisoformat(landed["at"].replace("Z", "+00:00"))
    return (now.astimezone(dt.timezone.utc) - at).total_seconds()


def clear(w: dict) -> list[dict]:
    """The field's resting session cleared once; no session: nothing to clear."""
    if not w["sessions"]:
        return []
    pane = w["sessions"][0]["pane_id"]
    return [act("prune", "barn-clear", "run", w["slot"], key=f"barn-clear:{w['slot']}:{w['head']}", window=ONCE,
                argv=CLEAR[:2] + ["--pane", pane] + CLEAR[2:],
                text=f"clear field {w['slot']}'s session {pane}: its crop is in the barn, its work is safe")]


def stuck(w: dict, landed: dict) -> dict:
    return act("prune", "barn-stuck", "wake", w["slot"], key=f"barn-stuck:{w['slot']}:{w['head']}", window=ONCE,
               text=f"field {w['slot']} rode train {landed.get('train')} into the barn over 24 h ago and still "
                    f"holds work: {w['why']}. Look; never remove it by force (new work of its foreman is fine)")


def actions(ctx: dict, found: list[dict], landed: dict | None) -> list[dict]:
    """The clears and the stuck wakes for the cars of the last landed train (removal stays /prune's)."""
    if not landed:
        return []
    fields, out = cars(landed), []
    late = age(landed, ctx["now"]) >= STUCK_AFTER
    for w in found:
        if w["slot"] not in fields or not Path(w["path"]).is_dir():
            continue
        if w["why"]:
            out += [stuck(w, landed)] if late else []
        elif int(w["slot"]) < 10 and cleaned(ctx.get("log", []), w["slot"], w["head"]):
            out += clear(w)
    return out
