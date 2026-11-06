#!/usr/bin/env python3
"""The draft: the train the queue allows now, steps 1 to 4 of trains.py's module doc (hal2 plan 0294 step 6), split
out of trains.py by plan 0610 step 1 (small-files). Every hitched wagon rides (the user, 2026-11-04: "take all
finished ones into the train"; plan 0610 D1, D7, D20): a ready ticket ends as a car, or under one of the user-named
EXCEPTIONS, never else.

1. the tickets marked `ready`, in queue order; only adjacent production wagons ride: a smuggle entry passes alone,
   one between them cuts the train (kinds.py, plan 0375 D8)
2. nothing is unhitched (the user, 2026-11-04: "when a car has hitched, it will never leave the queue again"): a
   head in the barn already, a servant's field (`plans/LEAD`) and a ticket in its own landing wait, hitched
   (trains_sort.sort_out); a worktree that is gone rides from its hitched sha (a board note tells the farmer,
   trains.train_actions). A place the user reserved for a field that is not ready holds the wagons
   behind it (.adr/merge-queue-policy.md rule 2); a place the queue watch put back holds nobody (leavers.py, E18)
3. a head the carrier holds already (an ancestor of the draft's base or of a `carried` commit: the standing train's
   carrier) is a car with `carried`, never trial-merged or proven again (plan 0610 E9, E30)
4. the alone rule (plan 0333 D11, D12; gate_car.py): a car that adds, removes or renames the landing workflow or
   changes what starts its run holds nobody: the others form now, it waits for its own train right after them
   (`alone_next`, on the train's `formed` line), ahead of every later hitch (plan 0610 D9, D15). It rides alone now
   when it is owed (`first`: the last formed train's `alone_next`), when fewer than `minimum` are hitched, or when no
   other car rides; then every other wagon waits for the train after it
5. the minimum (plan 0610 D11, trains.MIN_HITCHED; the user, 2026-10-31: "I said at least 10 hitched fields ... So
   it should be 10 plus."): with fewer hitched fields every wagon waits (`minimum`), unless an alone car rides
6. the trial merge in queue order (trial.py; no car limit unless the user's standing `max-cars <n>`: the first n ride,
   the rest wait, hitched, for a later train, plan 0695 D62): a conflict, not only in generated files, is
   a car with `conflict` and `ahead` (plan 0522 D18); a trial that cannot run is tried once more, then the car rides
   `untried` and `engine.py form` merges it (E15); before it the wagons are ordered by the farm's plan dependencies
   (train_depends.py, plan 0595 D22: a dependent behind its dependency, never left out; the draft's `depends`).
   The light checks (proof.py): red rides with `proof_red`, fixed in
   the train (proof_orders.py); `wait` rides with `proof_unknown`, the pretest and the gate run the checks (E16); the
   lines the barn's own head shows too are the draft's `barn_red`, the barn's own fix order, never a car's (field 79
   row 13)
7. the closing pass (`close`, plan 0610 D20): a ticket in `waiting` or `unhitched` whose `reason` is no EXCEPTION, or
   in no list at all, is moved into the cars, after its dependency (`after`) when that rides
"""

from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import gate_car
import generated
import kinds
import train_depends
import train_wt
import trial as trial_merge
from trains_sort import HELD, current_plan, held_ahead, sort_out

# The only reasons a hitched wagon is not a car of this train, each the user's (plan 0610 D7, D20; ROLE.md's words).
EXCEPTIONS = {
    "servant": "a servant's field never lands (~/.claude/GLOSSARY.md: servant)",
    "barn": "its head is in the barn already: nothing to land",
    "smuggle": "its entry smuggles itself (plan 0375: merge trains only for official hitches)",
    "smuggler-ahead": "a smuggler passes alone before it (ROLE.md, plan 0375: \"they should just go alone\")",
    "asleep": "the tollman sleeps (plan 0375: no merge trains while he is not awake)",
    "reserved": "a place the user reserved stands ahead of it (.adr/merge-queue-policy.md rule 2)",
    "hold": "the user's hold (hold.py, with the user's words)",
    "own-landing": "its own landing runs",
    "alone": "the alone car's own train, right after this one (plan 0610 D9, D15)",
    "max-cars": "the user's standing max-cars: the train is full, the wagon rides a later one (standing.py; hitch-is-forever)",
    "minimum": "fewer than 10 fields are hitched (the user, 2026-10-31: \"I said at least 10 hitched fields ... So it "
               "should be 10 plus.\"; plan 0610 D11)",
}
MAX_CARS = "a train takes at most {n} cars (the user's standing max-cars): it rides a later train"
MINIMUM = "{n} of {minimum} fields hitched: a train forms once {minimum} are, and takes every one (plan 0610 D11)"


def draft(main: str, tickets: list[dict], own: str, base: str, default: str, mode: dict | None, prove,
          carried=(), first=(), minimum: int = 0, max_cars: int = 0) -> dict:
    """{base, cars ([{field, branch, head, plan, ...}] in order), unhitched (always [], kept for its readers),
    waiting ([{field, why, reason}]), alone (the one car rides alone), alone_next (the alone cars that wait for their
    own train), barn_red ([{field, lines}])}. `prove` is trains.PROVE; `carried`: commits whose ancestors ride already
    (the standing train's carrier head); `first`: the alone cars owed their train now; `minimum`: the hitched fields
    a train needs (0: none, the open train's joins); `max_cars`: the user's standing cap on the cars (0: none; the rest
    wait, hitched, for the next train)."""
    rides, later = kinds.split(tickets, own, mode)
    wagons, kept = sort_out(main, default, rides, own)  # they wait, hitched (never unhitched, the user 2026-11-04)
    deps = train_depends.read(main) if wagons else train_depends.NONE  # a dependent behind its dependency (0595 D22)
    wagons = train_depends.order(wagons, deps)
    out = {"base": base, "cars": [], "unhitched": [], "alone": False, "alone_next": [], "barn_red": [],
           "waiting": kept + later, "depends": []}  # kinds.split names each one's reason
    alone, plain, holders = [], [], [r for r in (base, *carried) if r and r != default]
    for t in wagons:
        field, head = t["slot"], t["ready"]["head"]
        if held := held_ahead(tickets, own, t):  # only a place ahead of it (L95)
            out["waiting"].append({"field": field, "why": HELD.format(field=held), "reason": "reserved"})
        elif any(trial_merge.git(main, "merge-base", "--is-ancestor", head, r)[0] == 0 for r in holders):
            out["cars"].append(car(t, carried=True))  # in the carrier already: a car, never proven again (E9)
        elif why := gate_car.alone_why(main, default, head):
            alone.append((t, why))
        else:
            plain.append(t)
    n = hitched(tickets, own) - sum(k["reason"] == "barn" for k in kept)  # a head in the barn is landed (D21)
    owed = [x for x in alone if x[0]["slot"] in first]
    lead = (owed or alone)[0] if alone and (owed or n < minimum or not (plain or out["cars"])) else None
    if lead:  # the carried cars stay: their heads are in the base already
        alone.remove(lead)
        out["alone"] = True
        ride(main, lead[0], base, base, default, prove, out)
        out["waiting"] += [{"field": t["slot"], "why": f"rides after {lead[0]['slot']}, which rides alone: {lead[1]}",
                            "reason": "alone"} for t in plain]
    elif n < minimum:
        out["waiting"] += [{"field": f, "why": MINIMUM.format(n=n, minimum=minimum), "reason": "minimum"}
                           for f in [c["field"] for c in out["cars"]] + [t["slot"] for t in plain]]
        out["cars"] = []
    else:
        acc = base
        for t in plain:
            if max_cars and len(out["cars"]) >= max_cars:  # full: it keeps its place for a later train
                out["waiting"].append({"field": t["slot"], "why": MAX_CARS.format(n=max_cars), "reason": "max-cars"})
                continue
            acc = ride(main, t, acc, base, default, prove, out)
    after = f"after {lead[0]['slot']}, which rides alone" if lead else "right after this one"
    out["waiting"] += [{"field": t["slot"], "why": f"rides alone in its own train, {after}: {why}", "reason": "alone"}
                       for t, why in alone]
    out["alone_next"] = [] if lead else [t["slot"] for t, _ in alone]  # after an alone train the others go first (D9)
    out = close(tickets, own, out)
    out["depends"] = train_depends.lines(deps, out["cars"])
    return out


def hitched(tickets: list[dict], own: str) -> int:
    """The fields hitched now (a ready mark), the tollman's own and the trains' worktrees left out."""
    return sum(1 for t in tickets if t.get("ready") and t.get("slot") != own and not train_wt.is_train(t.get("slot")))


def car(t: dict, **flags) -> dict:
    """A ticket as a car: {field, branch, head, plan}, `gone` when its worktree is (E13: every way in, the board note
    follows) and the flags that are set."""
    here = Path(worktree(t)).is_dir()
    plan = current_plan(t["worktree"]) if here else ""
    return {"field": t["slot"], "branch": t.get("branch") or t["slot"], "head": t["ready"]["head"], "plan": plan,
            **open_plan(t), **{k: v for k, v in {**flags, "gone": not here}.items() if v}}


def open_plan(ticket: dict) -> dict:
    """{"milestone": label} for a ticket whose plan stays open after the landing (plan 0593 step 4, 0592 D10), read
    from the queue's `plan.hitch` ("milestone 1/2"; a partial override), never recomputed; else {}."""
    hitch = (ticket.get("plan") or {}).get("hitch") or {}
    kind = hitch.get("kind")
    if kind not in ("milestone", "partial"):
        return {}
    return {"milestone": hitch.get("label") or (kind + " (override)")}


def worktree(t: dict) -> str:
    """The ticket's worktree, else a path that never exists, named by its field (the proof's cache key): proof.py
    proves such a field from the main checkout (E13), never `wait` for a missing path ("" is the current folder)."""
    return t.get("worktree") or f"/nonexistent-worktree/{t['slot']}"


def ride(main: str, t: dict, acc: str, base: str, default: str, prove, out: dict) -> str:
    """The wagon `t` a car of `out` (trial merge onto `acc`, light checks); the trial's head the next is merged onto."""
    head, c = t["ready"]["head"], car(t)
    out["cars"].append(c)
    proven = prove(main, worktree(t), head, default)
    if proven["state"] == "red":  # rides, fixed in the train by its order (proof_orders.py)
        c["proof_red"] = proven["lines"]
    elif proven["state"] == "wait":  # rides; the pretest and the gate run the checks (E16)
        c["proof_unknown"] = proven["lines"]
    if proven.get("barn_red"):  # the barn's own red: its fix order, never the car's (field 79 row 13)
        out["barn_red"].append({"field": c["field"], "lines": proven["barn_red"]})
    commit, files = trial_merge.merge(main, acc, head)
    if commit is None:
        commit, files = trial_merge.merge(main, acc, head)  # once more (E15)
    if commit is None:
        c["untried"] = f"the trial merge of {head[:12]} could not run: `form` merges it"
        return acc
    if files and not generated.only(main, base, files, commit):  # rides, resolved in the train (D18)
        barn = acc == base or bool(trial_merge.merge(main, base, head)[1])
        c.update(conflict=files, ahead=[] if barn else [x["field"] for x in out["cars"][:-1]])
        return acc
    return commit  # generated only: the train writes them again


def close(tickets: list[dict], own: str, out: dict) -> dict:
    """The closing pass (plan 0610 D20): every ready ticket of ours a car or under an EXCEPTION; any other entry of
    `waiting` or `unhitched`, and a ready ticket in no list, becomes a car (`moved_in`, `proof_unknown`), after its
    `after` field when that rides (one moved in too goes first), else at the end, in queue order; behind a car that
    rides alone it waits for the alone car's train."""
    moved = []
    for name in ("waiting", "unhitched"):
        moved += [x for x in out[name] if x.get("reason") not in EXCEPTIONS]
        out[name] = [x for x in out[name] if x.get("reason") in EXCEPTIONS]
    known = {x["field"] for name in ("cars", "waiting", "unhitched") for x in out[name]} | {m["field"] for m in moved}
    for t in sorted(tickets, key=lambda t: t.get("position", 0)):
        f = t.get("slot")
        if t.get("ready") and f != own and not train_wt.is_train(f) and f not in known:
            moved.append({"field": f, "why": "the draft gave no reason"})
    by = {t.get("slot"): t for t in tickets if t.get("ready")}
    seen, pending = {c["field"] for c in out["cars"]}, []
    for m in sorted(moved, key=lambda m: by.get(m["field"], {}).get("position", 0)):  # in queue order
        if m["field"] in by and m["field"] not in seen:
            seen.add(m["field"])
            pending.append(m)
    while pending:  # a car whose dependency is moved in too waits for it (a cycle: queue order)
        ready = [m for m in pending if m.get("after") not in {p["field"] for p in pending if p is not m}] or pending[:1]
        for m in ready:
            pending.remove(m)
            place(by[m["field"]], m, out)
    return out


def place(t: dict, m: dict, out: dict) -> None:
    """The moved-in ticket `t` a car after its `after` field when that rides, else last; behind an alone car it
    waits."""
    if out["alone"]:
        out["waiting"].append({"field": m["field"], "why": f"rides after {out['cars'][-1]['field']}, which rides alone "
                               f"({m['why']})", "reason": "alone"})
        return
    c = car(t, moved_in=m["why"], proof_unknown=[f"moved in by the closing pass: {m['why']}"])
    at = next((i + 1 for i, x in enumerate(out["cars"]) if x["field"] == m.get("after")), len(out["cars"]))
    out["cars"].insert(at, c)
