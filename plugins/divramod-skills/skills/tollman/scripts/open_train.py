"""The open train (hal2 plan 0490 step 20; D20, D21, D23; plan 0610 D17, audit E3-E6, E8, E10; plan 0687 D1, D4): a
standing train takes every newly hitched wagon only until its first start (`fixed`: its `starts` count, raised by
every `started` line, train_fold.py); from then on its cars are fixed, in every state (landing, red, fixing, retry,
resolving): nothing joins, a riding car's newer head neither, a wagon hitched later rides the next train (the user,
2026-11-05: "When the train is rolling you can't join it"; plan 0687 D1 supersedes plan 0610 D17 for started trains).
A car recorded as joined before the cut still rides: the restart merges it (engine.restart: resolve_train.merge_rest,
plan 0687 D4). Nothing ever leaves the train (frozen.py, plan 0360 D3) and nothing is declined (E6): a join only adds.
A formed train never started joins as below; to a started train the round and the landing's `take` add no car, they
only owe its alone cars (`owe`, D15, below).

`joiners` drafts the hitched wagons on the carrier's head as the round's draft does (trains.draft: queue order, a
place the user holds ahead, adjacent production wagons only, the trial merge, the proof, the alone rule, no minimum):
every car of it joins, with what it needs (`conflict`, `proof_red`, `proof_unknown`, `untried`, `carried`: a hand
merge the carrier holds already is recorded so, E8). A riding field whose ticket holds a newer head joins again: its
newer head takes its car's place (E10). The train's own cars at their heads stay out.

- Before the first start (`OPEN`, never started): the round (trains.plan) runs `tollman.py join <field> --car <json>`
  per joiner (train_join.record): a `joined` line (`merged` false) and the queue's mark; the first start merges it
  (engine.restart: resolve_train.merge_rest, a conflict waits `resolving` with its resolve order), and a car with red
  light checks makes that start red with its fix order first (proof_orders.py). In `resolving` the carrier stays as
  it is until the resolve; `merge_rest` merges the joiners behind it.
- In its landing (`take`, the landing's own process: next_train.before_push each poll of its wait, of the fix wait,
  and once more right before the push): a landing has started, so nothing joins (plan 0687 D1; the landing's own join
  with its pretest is gone since plan 0687 step 2); `take` only owes the alone cars hitched meanwhile (`owe`).
  `stops` (engine.land, right before the push) still guards the joins recorded before the cut (D4): the push waits
  while a joined car waits for its resolve, a car is unmerged (the landing ends `interrupted`, the restart merges it)
  or a car's light checks are red with no fix order yet (the train goes red `proof_red`).

Nothing joins in smuggle mode or while the sleep flag stands, under the user's hold, to a train without a number, or
to a train whose car rides alone (gate_car.py); a wagon that would ride alone waits for its own train (D9): hitched
while the train stands, it goes on that train's `alone_next` (`owe`, an `alone` line; the round's `tollman.py join
<field> --alone`), so it rides alone in the very next train (D15); after the first start too (`started_alone`: only
gate_car.alone_why per candidate, no draft).
"""

import json
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import frozen
import gate_car
import hold
import modes
import mtm_scan
import proof_orders
import train_branch
import train_state
from carrier import git
from tick import default_ref

OPEN = ("formed", "resolving", "red", "fixing", "retry")  # a join is recorded (train_join.record), merged at the start


def fixed(train: dict) -> bool:
    """Whether the standing train has started at least once: its cars are fixed, nothing joins (plan 0687 D1)."""
    return bool(train.get("starts"))


def pushed(train: dict) -> bool:
    """Whether the standing train's current start pushed (its `push` line): no join after it."""
    return train.get("state") == "landing" and bool(train.get("head"))


def take(top: str, main: str) -> list[str]:
    """The landing's round (the carrier `top`, the landing's own process, before the push): a landing's train has
    started, its cars are fixed (plan 0687 D1), so it adds no car; each wagon hitched meanwhile that rides alone is
    owed the very next train (`owe`, plan 0610 D15). The lines printed."""
    train = train_state.standing(train_state.lines(main))
    if not train or train["carrier"] != Path(top).name or train["state"] != "landing" or pushed(train) \
            or not train_branch.numbered(train):
        return []
    doc = mtm_scan.run_json(mtm_scan.QUEUE, main) or {}
    if modes.asleep(modes.of(doc), doc.get("queue", []), modes.flag(main)) or hold.of(main):
        return []
    lines = owe(main, train, started_alone(main, train, doc.get("queue", [])))
    for text in lines:
        print(text, flush=True)
    return lines


def candidates(main: str, train: dict, tickets: list[dict]) -> list[dict]:
    """The hitched tickets that may join: a field no car of the train, or a riding field whose ready head is newer than
    its car's (E10); a car at its own head, or an older head of it, never."""
    heads, out = {c["field"]: c["head"] for c in train["cars"]}, []
    for t in tickets:
        head = (t.get("ready") or {}).get("head")
        old = heads.get(t.get("slot"))
        if not head or head == old or old and git(main, "merge-base", "--is-ancestor", head, old)[0] == 0:
            continue
        out.append(t)
    return out


def draft(main: str, top: str, train: dict, tickets: list[dict], mode: dict | None) -> dict | None:
    """The round's draft on the carrier's head for the candidates, or None (the train started once, plan 0687 D1; no
    candidate; or the train has a car that rides alone)."""
    import trains  # the round's draft: loaded only when a wagon may join
    if fixed(train) or not (them := candidates(main, train, tickets)):
        return None
    default, carrier = default_ref(main), Path(top).name
    if any(gate_car.alone_why(main, default, c["head"]) for c in train["cars"]):
        return None
    head = git(top, "rev-parse", "HEAD")[1]
    return trains.draft(main, them, carrier, head, default, mode)


def joiners(main: str, top: str, train: dict, tickets: list[dict], mode: dict | None) -> list[dict]:
    """Every car the draft takes now (`draft`), a conflict and red light checks too (E5); none when the first of them
    rides alone (it waits for its own train)."""
    return round_of(main, top, train, tickets, mode)[0]


def round_of(main: str, top: str, train: dict, tickets: list[dict], mode: dict | None) -> tuple[list[dict], list[dict]]:
    """One draft's joiners and its alone cars ({field, head, why}: a wagon that would ride alone, hitched while the
    train stands, rides alone in the very next train, plan 0610 D15), the train's own owed ones left out. A started
    train (plan 0687 D1): no joiner, only its alone cars (`started_alone`)."""
    if fixed(train):
        return [], started_alone(main, train, tickets)
    if not (d := draft(main, top, train, tickets, mode)):
        return [], []
    heads = {t.get("slot"): (t.get("ready") or {}).get("head") for t in tickets}
    whys = {w["field"]: w["why"] for w in d["waiting"] if w.get("reason") == "alone"}
    fields = [c["field"] for c in d["cars"]] if d["alone"] else d["alone_next"]
    owed = set(owed_now(train_state.lines(main)))
    alone = [{"field": f, "head": heads.get(f), "why": whys.get(f) or "it rides alone (gate_car.py)"}
             for f in fields if heads.get(f) and f not in owed]
    return ([] if d["alone"] else d["cars"]), alone


def started_alone(main: str, train: dict, tickets: list[dict]) -> list[dict]:
    """The alone cars of a started train (plan 0687 D1 keeps plan 0610 D15): each new field among the candidates whose
    head rides alone (gate_car.alone_why), not owed yet; none when a car of the train rides alone (as `draft`)."""
    riding = {c["field"] for c in train["cars"]}
    if not (them := [t for t in candidates(main, train, tickets) if t.get("slot") not in riding]):
        return []
    default, owed = default_ref(main), set(owed_now(train_state.lines(main)))
    them = [t for t in them if t.get("slot") not in owed]
    if not them or any(gate_car.alone_why(main, default, c["head"]) for c in train["cars"]):
        return []
    whys = [(t, gate_car.alone_why(main, default, t["ready"]["head"])) for t in them]
    return [{"field": t["slot"], "head": t["ready"]["head"], "why": why} for t, why in whys if why]


def actions(top: str, main: str, train: dict | None, tickets: list[dict], mode: dict | None) -> list[dict]:
    """The open train's join round outside its landing (trains.join_actions; plan 0610 D17, E3, E4: every round while
    it stands before its first start; after it only its alone cars, plan 0687 D1): a `tollman.py join <field> --car
    <json>` per joiner, each a car from then on, merged by the train's next start (train_join.record), and a
    `tollman.py join <field> --alone <json>` per alone car (`owe`, D15). Its landing owes them in its own process
    (`take`)."""
    import trains  # its `run` actions; trains loads this module only while a train stands
    import train_wt
    at = train_wt.folder(train, top) if train else ""
    if not train or train["state"] not in OPEN or train_wt.astray(at, train) or not Path(at).is_dir():
        return []
    cars, alone = round_of(main, at, train, tickets, mode)
    name, state = train["train"], train["state"]
    owe_runs = [trains.run("join", "-", f"alone:{name}:{c['field']}@{c['head'][:12]}", "join", top, c["field"],
                           "--alone", json.dumps(c), window=0, script=trains.TOLLMAN,
                           text=f"open train {name} ({state}): field {c['field']} rides alone in the very next train, "
                                "its own (plan 0610 D15)") for c in alone]
    flags = lambda c: "".join(f", {k}" for k in trains.JOIN_FLAGS if c.get(k))  # noqa: E731
    return owe_runs + [trains.run("join", "-", f"join:{name}:{c['field']}@{c['head'][:12]}", "join", top, c["field"],
                                  "--car", json.dumps(c), window=0, script=trains.TOLLMAN,
                                  text=f"open train {name} ({state}): field {c['field']} joins{flags(c)}")
                       for c in cars]


def owed_now(rows: list[dict]) -> list[str]:
    """The alone cars owed their own train next: the last `formed` line's `alone_next`, then every `alone` line after
    it (plan 0610 D15; trains.owed)."""
    out: list[str] = []
    for e in rows:
        if e.get("kind") == "formed":
            out = list(e.get("alone_next") or [])
        elif e.get("kind") == "alone" and e.get("field") and e["field"] not in out:
            out.append(e["field"])
    return out


def owe(main: str, train: dict, cars: list[dict], now=None) -> list[str]:
    """Each alone car not owed yet put on the standing train's `alone_next` (an `alone` line): its lines."""
    lines, owed = [], set(owed_now(train_state.lines(main)))
    for c in cars:
        if c["field"] in owed:
            continue
        train_state.append(main, "alone", train["carrier"], now, train=train["train"], field=c["field"],
                           head=c["head"], why=c["why"])
        owed.add(c["field"])
        lines.append(f"open train {train['train']}: field {c['field']} rides alone in the very next train, its own "
                     f"({c['why']})")
    return lines


def stops(top: str) -> int:
    """engine.land's look right before the push (the module doc): 1 when the push waits, with its line printed; it
    guards the joins recorded before the first start (plan 0687 D4)."""
    main = mtm_scan.main_checkout(top)
    train = train_state.standing(train_state.lines(main))
    if not train:
        return 0
    if train["state"] == "resolving":
        print(f"tollman: train {train['train']} is resolving: a car that joined waits for its resolve, no push",
              flush=True)
        return 1
    if lacking := frozen.lacking(top, train):
        print(json.dumps({"status": "interrupted", "message": f"car {', '.join(lacking)} joined unmerged: the next "
                          "start merges it"}), flush=True)
        return 1
    if red := proof_orders.red_line(main, Path(top).name, train):
        print(json.dumps({"status": proof_orders.STATUS, "message": red[:300]}), flush=True)
        return 1
    return 0

