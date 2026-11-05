"""`tollman.py cars [--json]` (hal2 plan 0610 D8b): the standing train's cars and every hitched wagon with where it
stands, read by code from the queue, the train state and the train's branch, never from memory or a model's guess. No
proof and no trial merge run (`tollman.py train --dry-run` does them); nothing is written.

  {schema, train: {train, number, state, carrier, head, pushed, open} | null,
   cars: [{field, head, plan, in_branch, ...the car's flags}],
   hitched: [{field, head, where, why, reason}]}

`where` of a hitched wagon: `car` (a car of the standing train at this head), `in-branch` (the train's branch holds
the head but it is no car yet: the next join round records it, E8), `joins` (the train is open: it joins at the next
join round, before the push, D17), `next` (the train pushed, or is paused or split: it rides the next train), `forms`
(no train stands: it rides the next one), `waits` (a user-named exception: `reason` is trains_draft.EXCEPTIONS' key;
an alone car owed the very next train, its own, `alone`: plan 0610 D15).
"""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import hold
import kinds
import modes
import mtm_scan
import open_train
import train_state
import train_wt
from carrier import git
from tick import default_ref
from trains_draft import EXCEPTIONS, MINIMUM, hitched
from trains_sort import HELD, held_ahead, sort_out

SCHEMA = 1
OWED = "rides alone in the very next train, its own, right after this one (plan 0610 D15)"
FLAGS = ("conflict", "proof_red", "pretest_red", "proof_unknown", "untried", "carried", "gone", "moved_in")


def of(repo: str) -> dict:
    """The cars and the hitched (the module doc)."""
    import trains  # the minimum; loaded only by this command
    main = mtm_scan.main_checkout(repo)
    own = mtm_scan.roles.slot_dir(main, train_state.ROLE).name
    rows = train_state.lines(main)
    train, doc = train_state.standing(rows), mtm_scan.run_json(mtm_scan.QUEUE, main) or {}
    tickets, mode, default = doc.get("queue", []), modes.of(doc), default_ref(main)
    folder = train_wt.folder(train, "") if train else ""
    head = git(folder, "rev-parse", "HEAD")[1] if folder else ""
    holds = lambda h: bool(head) and git(main, "merge-base", "--is-ancestor", h, head)[0] == 0  # noqa: E731
    out = {"schema": SCHEMA, "train": None, "cars": [], "hitched": []}
    if train:
        out["train"] = {"train": train["train"], "number": train.get("number"), "state": train["state"],
                        "carrier": train["carrier"], "head": head or None, "pushed": open_train.pushed(train),
                        "open": train["state"] in open_train.OPEN or train["state"] == "landing"
                        and not open_train.pushed(train)}
        out["cars"] = [{"field": c["field"], "head": c["head"], "plan": c.get("plan") or "",
                        "in_branch": holds(c["head"]), **{k: c[k] for k in FLAGS if c.get(k)}} for c in train["cars"]]
    heads = {c["field"]: c["head"] for c in (train or {}).get("cars", [])}
    waits = why_waits(main, default, tickets, own, mode)
    if train:  # an alone car hitched while it stands: its own train is the very next (plan 0610 D15)
        waits.update({f: {"why": OWED, "reason": "alone"} for f in open_train.owed_now(rows) if f not in waits})
    n = hitched(tickets, own)
    for t in sorted(tickets, key=lambda t: t.get("position", 0)):
        field, h = t.get("slot"), (t.get("ready") or {}).get("head")
        if not h or field == own or train_wt.is_train(field):
            continue
        out["hitched"].append({"field": field, "head": h, **where(train, out["train"], field, h, heads, waits, holds,
                                                                  n, trains.minimum(main), main)})
    return out


def why_waits(main: str, default: str, tickets: list[dict], own: str, mode: dict | None) -> dict:
    """{field: {why, reason}} of the hitched that wait under a user-named exception now (no proof, no trial)."""
    if modes.asleep(mode, tickets, modes.flag(main)):
        return {t["slot"]: {"why": EXCEPTIONS["asleep"], "reason": "asleep"} for t in tickets if t.get("ready")}
    if held := hold.of(main):
        return {t["slot"]: {"why": hold.text(held), "reason": "hold"} for t in tickets if t.get("ready")}
    rides, later = kinds.split(tickets, own, mode)
    wagons, kept = sort_out(main, default, rides, own)
    out = {x["field"]: {"why": x["why"], "reason": x["reason"]} for x in kept + later}
    for t in wagons:
        if at := held_ahead(tickets, own, t):
            out[t["slot"]] = {"why": HELD.format(field=at), "reason": "reserved"}
    return out


def where(train, info, field, head, heads, waits, holds, n, minimum, main) -> dict:
    """One hitched wagon's `where`, `why` and `reason` (the module doc)."""
    name = (train or {}).get("train")
    old = heads.get(field)
    if old and (head == old or git(main, "merge-base", "--is-ancestor", head, old)[0] == 0):
        return {"where": "car", "why": f"a car of train {name}" + ("" if holds(old) else ", merged at its next start")}
    if field in waits:
        return {"where": "waits", **waits[field]}
    if train and holds(head):
        return {"where": "in-branch", "why": f"the branch of train {name} holds it but it is no car yet: the next join "
                                             "round records it (plan 0610 E8)"}
    if train and info["open"]:
        more = " as its car's newer head (E10)" if old else ""
        return {"where": "joins", "why": f"joins train {name} ({train['state']}){more} at its next join round, before "
                                         "its push (plan 0610 D17)"}
    if train:
        why = f"train {name} pushed" if info["pushed"] else f"train {name} is {train['state']}"
        return {"where": "next", "why": f"{why}: it rides the next train"}
    if n < minimum:
        return {"where": "waits", "why": MINIMUM.format(n=n, minimum=minimum), "reason": "minimum"}
    return {"where": "forms", "why": "no train stands: it rides the next one, formed at the next round"}


def show(d: dict) -> None:
    t = d["train"]
    print(f"train {t['train']} ({t['state']}{', pushed' if t['pushed'] else ', open' if t['open'] else ''}), carrier "
          f"{t['carrier']} at {(t['head'] or '?')[:12]}" if t else "no train stands")
    for c in d["cars"]:
        flags = "".join(f", {k}" for k in FLAGS if c.get(k))
        print(f"car {c['field']} ({c['plan'] or '-'}, {c['head'][:12]}{'' if c['in_branch'] else ', not merged yet'}"
              f"{flags})")
    for h in d["hitched"]:
        print(f"hitched {h['field']} ({h['head'][:12]}): {h['where']}: {h['why']}")
