"""The reconcile of a running delegation (hal2 plan 0618, D2-D4): whether the foreman the farmer started still works
on it. Pure: no git, no files, no clock; delegation_round.py gathers the facts once a round and applies the verdicts.

A running entry of `delegations.jsonl` is judged in this order (D3):
1. transplant: its field's work moved on (transplants.py) → still `running`, in the target field;
2. `gone`: the field list is known and the field is not in it;
3. `landed`: another delegation entered the field after it and is still there: a foreman only starts in a free
   field (no plan, nothing ahead), so this work had ended there (today's landing rule, held at that start); its
   session is the newer one's;
4. `landed`: its plan (recorded, else the field's) is done on main (`done`, `shipped`, `uat`);
5. `moved`: the field holds another numbered plan than its own, or (a legacy entry without `plan`) a plan created
   more than a day after the delegation started;
6. `landed`: settled, the field holds no plan and nothing ahead (today's rule);
7. else `running`, with the field's numbered plan to record when the entry has none yet (`plan`).

`working` then picks, of the running entries, those that use capacity (D6): a paused field or one without a live
session keeps its `running` state (it may resume) but does not count against the foreman limit.

Only a numbered CURRENT_PLAN (`<NNNN>-<slug>`) is a plan here: a task name a foreman writes before its plan exists
is never recorded nor compared.
"""

import datetime as dt
import re

import live_sessions
import roletime
import transplants

SETTLE = dt.timedelta(minutes=30)  # a foreman younger than this has not started its plan yet
DONE = ("done", "shipped", "uat")  # a plan status on main that says it has landed
NO_FIELD = ("waiting", "planned", "error")  # entry states that hold no field
PLAN = re.compile(r"^(\d{4}-[A-Za-z0-9._-]+)")


def plan_slug(text: str | None) -> str:
    """`0618-delegation-ledger-sync` for a CURRENT_PLAN text naming a plan (also `<plan>/...`), "" otherwise."""
    m = PLAN.match((text or "").strip())
    return m.group(1) if m else ""


def starts(lines: list[dict]) -> list[tuple[str, str, dt.datetime]]:
    """(key, field, at) for every time a delegation entered a field, in ledger order: its first note with a field, a
    move to another field (a transplant), or a start again after it had stopped running."""
    seen, out = {}, []
    for e in lines:
        key, slot, state = e.get("key"), e.get("slot"), e.get("state")
        if not key:
            continue
        before = seen.get(key, {})
        entered = slot != before.get("slot") or (state == "running" and before.get("state") != "running")
        if slot and state not in NO_FIELD and entered and (at := roletime.parse(e.get("at"))) is not None:
            out.append((key, slot, at))
        seen[key] = {"slot": slot or before.get("slot"), "state": state or before.get("state")}
    return out


def entry_facts(key: str, entry: dict, round_facts: dict) -> dict | None:
    """The facts `reconcile` reads for one running entry, from the round's (`delegation_round.gather`). None when
    the entry has no readable start (left as it is)."""
    slot, entered = entry["slot"], round_facts["starts"]
    start = max((at for k, s, at in entered if k == key and s == slot), default=None) or roletime.parse(entry.get("at"))
    if start is None:
        return None
    last = {k: s for k, s, _ in entered}  # where each delegation is now: one moved on by hand proves nothing here
    later = sorted((at, k) for k, s, at in entered if s == slot and k != key and at > start and last[k] == slot)
    return {"start": start, "moved_to": transplants.follow(round_facts["transplants"], slot, start)[0],
            "taken_by": (later[0][1], later[0][0]) if later else None, "known": round_facts["known"],
            "field": round_facts["fields"].get(slot), "main": round_facts["main"]}


def verdict(state: str, slot: str, reason: str, stop: bool = False, **more) -> dict:
    return {"state": state, "slot": slot, "reason": reason, "stop": stop, **more}


def created_late(created: str | None, start: dt.datetime) -> bool:
    """A plan created (`YYYY-MM-DD`) more than a day after the delegation's local start day: not its foreman's."""
    try:
        day = dt.date.fromisoformat(str(created))
    except ValueError:
        return False
    return day > start.astimezone().date() + dt.timedelta(days=1)


def reconcile(entry: dict, facts: dict, now: dt.datetime) -> dict:
    """The verdict on one running entry: `{state, slot, reason, stop, [from], [plan]}` (the ledger keys); `stop`
    only for a landing of the entry's own session (D4), `plan` the field's plan to record on a still running entry."""
    slot, start = entry["slot"], facts["start"]
    if facts.get("moved_to"):
        return verdict("running", facts["moved_to"], "transplanted", **{"from": slot})
    field = facts.get("field")
    if facts.get("known") and field is None:
        return verdict("gone", slot, f"field {slot} no longer exists")
    if facts.get("taken_by"):
        other, at = facts["taken_by"]
        return verdict("landed", slot, f"{other} started in field {slot} at {roletime.stamp(at)}: "
                                       "the field was free, so this work had ended")
    field = field or {}
    held, own = plan_slug(field.get("plan")), plan_slug(entry.get("plan"))
    record = ""
    if not own and held:
        if created_late(field.get("created"), start):
            return verdict("moved", slot, f"field {slot} holds {held}, created {field['created']}, after this delegation")
        own = record = held
    status = (facts.get("main") or {}).get(own) if own else None
    if status in DONE:
        return verdict("landed", slot, f"plan {own} is {status} on main", stop=True)
    if own and held and held != own:
        return verdict("moved", slot, f"field {slot} holds {held}, not {own}")
    if not field.get("plan") and not field.get("ahead") and now - start > SETTLE:
        return verdict("landed", slot, "the field holds no plan and nothing ahead", stop=True)
    return verdict("running", slot, "still working", **({"plan": record} if record else {}))


def working(entries: list[dict], facts: dict) -> list[dict]:
    """The running `entries` that really work (D6): their field is not paused and holds a live session. `facts`:
    {sessions: the agent list or None when unreadable, paused: {field: ...}, paths: {field: checkout path}}. Fail
    closed: with no readable session list, or a field whose path is unknown, the entry counts."""
    sessions, paused, paths = facts.get("sessions"), facts.get("paused") or {}, facts.get("paths") or {}
    out = []
    for e in entries:
        slot = e.get("slot")
        if slot in paused:
            continue
        path = paths.get(slot)
        if sessions is None or not path or live_sessions.live_session(sessions, path) is not None:
            out.append(e)
    return out
