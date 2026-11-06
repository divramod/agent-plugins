"""A join outside a landing and the standing train's cars (hal2 plan 0610 D8, D17; audit E3, E4, E8; plan 0687 D1):

  tollman.py join <field> [--car <json>] [--repo <dir>]
      the hitched head of `field` joins the standing train as a car (`record`): the round runs it per joiner with the
      car its draft made (open_train.joiners, `--car`); by hand (the session's, instead of a merge into the carrier:
      E8) without `--car`, the same draft decides, and a wagon that waits under a user-named exception is refused
      with its reason. Only a train never started takes a join: once it started (open_train.fixed, its first
      `started` line; plan 0687 D1, superseding plan 0610 D17 for started trains) `join` refuses before it touches
      anything, the wagon stays hitched and rides the next train
  tollman.py join <field> --alone <json> [--repo <dir>]
      a wagon that would ride alone (gate_car.py), hitched while the train stands: on that train's `alone_next` (an
      `alone` line, open_train.owe; plan 0610 D15), so it rides alone in the very next train, its own; the round runs it
  tollman.py cars [--json] [--repo <dir>]
      the standing train's cars and every hitched wagon with where it stands (train_cars.py), read from the queue,
      the train state and the train's branch by code: what every status answer reads

`record` is the join of a train that stands formed, never started (open_train.OPEN, open_train.fixed): a `joined` line
(`merged` false unless the carrier holds the head already, a hand merge) and the queue's mark with every car
(`--train/--attempt` of its last start; a refusal is noted, the next start marks it). The carrier is not touched: the
next start merges the car (engine.restart: resolve_train.merge_rest, a conflict waits `resolving` with its resolve
order) and makes the train red first when its light checks are red (proof_orders.red_line).
"""

import json
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import modes
import mtm_scan
import open_train
import records_kinds
import train_branch
import train_state
import train_wt
from carrier import Done, git

VERBS = ("join", "cars")


def record(top: str, main: str, train: dict, car: dict, now=None) -> Done:
    """The car joined to the standing train outside its landing (the module doc)."""
    import engine  # its `cli` (hal2-cli-git)
    carrier, name, state = Path(top).name, train["train"], train["state"]
    cars = train_state.add_cars(train["cars"], [car])
    mark = ["--train", str(train["number"]), "--attempt", str(max(1, train["starts"]))] \
        if train_branch.numbered(train) else []
    code, out = engine.cli(["worktree", "queue", "train", carrier, *(c["field"] for c in cars), *mark, "--json"], top)
    head = git(top, "rev-parse", "HEAD")[1]
    merged = git(top, "merge-base", "--is-ancestor", car["head"], head)[0] == 0  # a hand merge (E8)
    update = any(c["field"] == car["field"] for c in train["cars"])  # a riding field's newer head (E10)
    train_state.append(main, "joined", carrier, now, train=name, cars=[car], base=head, commit=head, merged=merged,
                       result="none", why=f"joined while {state}", mark=out[-200:] if code else None)
    what = f"field {car['field']} ({car.get('plan') or car['branch']}, {car['head'][:12]})"
    return 0, (f"open train {name} ({state}): {what} joined" + (" as its car's newer head" if update else "")
               + ("; the carrier holds it already" if merged else "; its next start merges it")
               + (f"; the queue refused the mark ({out[-120:]}): the next start marks it" if code else ""))


def join(repo: str, field: str, car: dict | None = None, now=None) -> Done:
    """`tollman.py join <field>`: see the module doc."""
    import engine
    main, _, train, top = engine.here(repo)
    if not train:
        return 1, f"no train stands: field {field} rides the next train's draft"
    name, state = train["train"], train["state"]
    if open_train.fixed(train):  # plan 0687 D1: the cars are fixed at the first start
        return 1, (f"train {name} started ({state}, start {train['starts']}): its cars are fixed, nothing joins (hal2 "
                   f"plan 0687 D1); field {field} stays hitched and rides the next train")
    if state not in open_train.OPEN:
        return 1, f"train {name} is {state}: nothing joins it now; field {field} rides the next train"
    if gone := train_wt.astray(top, train):
        return 1, gone
    hand = car is None
    if hand:
        doc = mtm_scan.run_json(mtm_scan.QUEUE, main) or {}
        tickets = doc.get("queue", [])
        d = open_train.draft(main, top, train, tickets, modes.of(doc)) or {"cars": [], "waiting": []}
        car = next((c for c in d["cars"] if c["field"] == field and not d.get("alone")), None)
        if not car:
            why = next((w["why"] for w in d["waiting"] if w["field"] == field), "")
            why = why or ("it rides alone (gate_car.py): its own train comes next" if d.get("alone") else
                          "a car of the train rides alone (gate_car.py): it rides the next train"
                          if open_train.candidates(main, train, [t for t in tickets if t.get("slot") == field])
                          else "it is not hitched, or the train carries its head already")
            return 1, f"field {field} does not join train {name}: {why}"
    if car["field"] != field:
        return 1, f"the car names field {car['field']}, not {field}"
    code, text = record(top, main, train, car, now)
    if hand and not code:  # the session's join: open until the car is in the train (plan 0611)
        records_kinds.add(main, "hand-merge", field, f"field {field} ({car['head'][:12]}) joined train {name} by hand",
                          event=records_kinds.train_event("joined", train=name, field=field), now=now, train=name,
                          head=car["head"])
    return code, text


def owe(repo: str, field: str, car: dict, now=None) -> Done:
    """`tollman.py join <field> --alone <json>`: the alone car hitched while the train stands put on its `alone_next`
    (open_train.owe, plan 0610 D15): it rides alone in the very next train."""
    import engine
    main, _, train, _ = engine.here(repo)
    if not train:
        return 1, f"no train stands: field {field} rides the next train's draft"
    if car.get("field") != field or not car.get("head"):
        return 1, f"the alone car names field {car.get('field')}, not {field}, or no head"
    lines = open_train.owe(main, train, [{"why": "it rides alone (gate_car.py)", **car}], now)
    return 0, "; ".join(lines) or f"field {field} is owed its own train next already"


def add_parser(sub) -> None:
    j = sub.add_parser("join")
    j.add_argument("field")
    j.add_argument("--car", type=json.loads, help="the car as the round's draft made it (open_train.joiners)")
    j.add_argument("--alone", type=json.loads, help="an alone car ({field, head, why}): owed the very next train")
    sub.add_parser("cars").add_argument("--json", action="store_true")


def main(args) -> int:
    if args.cmd == "cars":
        import train_cars
        d = train_cars.of(args.repo)
        print(json.dumps(d, indent=1)) if args.json else train_cars.show(d)
        return 0
    code, text = owe(args.repo, args.field, args.alone) if args.alone else join(args.repo, args.field, args.car)
    print(text, file=sys.stderr if code else sys.stdout)
    return code
