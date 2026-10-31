"""After the barn (hal2 plan 0360 step 7, D8): the fields of the last landed train, on the rounds after it.

The foreman of a car restocks, finishes its plan, mucks out and ends its turn ("in the barn", trains.TEXT); it does
not clear itself. The prune duty (prune.py) then looks at each car of the newest `landed` line of train.jsonl, on
/prune's facts (names-ok: slot, path, HEAD, the proof's refusal `why`, the field's live `sessions`; hal2 plan 0377 step 7, D12):
- a field 00-09 that /prune's proof finds free and that is mucked out (prune's `clean` ran for this HEAD: its key in
  the log, no exit) has its resting session cleared once: `hal2-cli-agents clear-and-continue --pane <pane>
  --without-plan --prompt /merge-from-main --detach`, key `barn-clear:<slot>:<HEAD>`. The facts are up to a round old
  (the plan is asked detached, plan 0480 D4), so the clear looks at the pane live first (`hal2-cli-agents list`): it
  clears only the field's live session in a resting state (idle, done, sleeping), else it waits for the next round. A
  draft in the box is not in the list; the clear job itself waits for it and never touches it;
- a field 10-99 is removed by /prune's run (stopped by signal, removed through the proof): its plan orders the
  last train's cars first, so a car is removed right after the barn (prune.py starts the run for it);
- a car whose field still holds work 24 hours after the landing: one wake, `barn-stuck:<slot>:<train>`, never a
  forced removal; none for a field whose CURRENT_PLAN names another plan than the car's that rode (its foreman's new
  work, L109: keyed by HEAD, every new commit of field 16's new research plan woke again).
"""

import datetime as dt
import re
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import live_sessions
import train_state
from tick import act

NUMBERED = re.compile(r"\d\d")  # a field 00-99 (a local copy: the tollman never imports /prune, plan 0377 D11)

STUCK_AFTER = 24 * 3600
ONCE = 30 * 24 * 3600
RESTING = {"idle", "done", "sleeping"}  # the states in which the session between two turns can be cleared
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


def live_agents() -> list[dict] | None:
    """`hal2-cli-agents list --json` now, None when it cannot be read (the farmer's one lookup, live_sessions.read)."""
    return live_sessions.read()


def resting_pane(w: dict, agents: list[dict] | None) -> str | None:
    """The pane of the field's one live session when it rests now, else None: no list, no session, or any of them busy
    or in a dialog (working, starting, blocked) is a reason to wait for the next round."""
    if agents is None:
        return None
    here = live_sessions.key(w["path"])
    mine = [a for a in agents if a.get("checkout") and live_sessions.key(a["checkout"]) == here and live_sessions.live(a)]
    if not mine or any(a.get("state") not in RESTING for a in mine):
        return None
    return mine[0].get("pane_id")


def clear(w: dict, agents: list[dict] | None) -> list[dict]:
    """The field's resting session cleared once, on the pane the live list names; the prune facts only say there was one."""
    pane = resting_pane(w, agents) if w["sessions"] else None
    if not pane:
        return []
    return [act("prune", "barn-clear", "run", w["slot"], key=f"barn-clear:{w['slot']}:{w['head']}", window=ONCE,
                argv=CLEAR[:2] + ["--pane", pane] + CLEAR[2:],
                text=f"clear field {w['slot']}'s session {pane}: its crop is in the barn, its work is safe")]


def rode(main: str, landed: dict) -> dict[str, str]:
    """{field: the plan its car carried} from the `formed` line of the landed train (`joined` cars too)."""
    out: dict[str, str] = {}
    for e in train_state.lines(main):
        if e.get("train") == landed.get("train") and e.get("kind") in ("formed", "joined"):
            out.update({str(c.get("field")): c.get("plan") or "" for c in e.get("cars", []) if isinstance(c, dict)})
    return out


def new_plan(w: dict, plan: str) -> bool:
    """The field's CURRENT_PLAN names a plan, and not the one its car carried."""
    try:
        now = (Path(w["path"]) / "plans" / "CURRENT_PLAN").read_text().strip()
    except OSError:
        return False
    return bool(now and plan and now != plan)


def stuck(w: dict, landed: dict) -> dict:
    return act("prune", "barn-stuck", "wake", w["slot"], key=f"barn-stuck:{w['slot']}:{landed.get('train')}", window=ONCE,
               text=f"field {w['slot']} rode train {landed.get('train')} into the barn over 24 h ago and still "
                    f"holds work: {w['why']}. Look; never remove it by force (new work of its foreman is fine)")


def actions(ctx: dict, found: list[dict], landed: dict | None) -> list[dict]:
    """The clears and the stuck wakes for the cars of the last landed train (removal stays /prune's)."""
    if not landed:
        return []
    fields, out = cars(landed), []
    late = age(landed, ctx["now"]) >= STUCK_AFTER
    agents, plans = [], None  # the live list, read when the first clear is due; the cars' plans, at the first stuck
    for w in found:
        if w["slot"] not in fields or not Path(w["path"]).is_dir():
            continue
        if w["why"]:
            plans = plans if plans is not None or not late else rode(ctx["main"], landed)
            out += [stuck(w, landed)] if late and not new_plan(w, (plans or {}).get(w["slot"], "")) else []
        elif int(w["slot"]) < 10 and cleaned(ctx.get("log", []), w["slot"], w["head"]):
            if not agents:
                agents.append(live_agents())
            out += clear(w, agents[0])
    return out
