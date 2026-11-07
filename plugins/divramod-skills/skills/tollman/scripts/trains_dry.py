"""`tollman.py train --dry-run` (hal2 plan 0294 step 6): the train that stands and trains.py's steps 1 to 4 for
the next one, with what the yard would give it; nothing is written, merged or sent. A train that stands: its cars
are left out of the next one, and a hitched head its carrier holds already (a hand merge) is listed `riding` it,
never proven again (plan 0610 E9)."""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import frozen
import modes
import mtm_scan
import open_train
import train_state
import train_wt
import trial as trial_merge
import yard_report
from tick import default_ref
import trains
from trains import QUEUE, ROLE, base_of, draft, owed


def dry_run(repo: str) -> dict:
    """`tollman.py train --dry-run`: the train that stands and steps 1 to 4 for the next one (without the cars
    that ride the standing one), and what the yard would give it (`yard`: placed and left); nothing is written,
    merged or sent. From any checkout of the farm: the field is the tollman's when it exists."""
    main = mtm_scan.main_checkout(repo)
    top = mtm_scan.roles.slot_dir(main, ROLE)
    rows, default = train_state.lines(main), default_ref(main)
    train = train_state.standing(rows)
    gone = bool(train and train["state"] == "split" and frozen.by_user(train))  # the user's split: the rest forms again
    rides = {c["field"] for c in train["cars"]} if train and not gone else set()
    doc = mtm_scan.run_json(QUEUE, main) or {}
    tickets = [t for t in doc.get("queue", []) if t.get("slot") not in rides]
    head = (train or {}).get("base") or (trial_merge.git(str(top), "rev-parse", "HEAD")[1] if top.is_dir() else None)
    carrier = trial_merge.git(train_wt.folder(train, str(top)), "rev-parse", "HEAD")[1] if train else ""
    d = draft(main, tickets, top.name, base_of(main, default, head), default, modes.of(doc),
              carried=[h for h in (carrier, (train or {}).get("head")) if h], first=[] if train else owed(rows),
              minimum=0 if train else trains.minimum(main),  # a standing train: what joins it (no minimum, 0610 D17)
              riding=sorted(rides) if train and not open_train.fixed(train) else ())  # its cars count (0722 D2)
    if train:  # what the standing carrier holds rides it (E9): no car of the next train
        d["riding"] = [c for c in d["cars"] if c.get("carried")]
        d["cars"] = [c for c in d["cars"] if not c.get("carried")]
    return {"field": top.name, "standing": train, **d,
            "yard": yard_report.seen(main, d["base"], default, d["cars"], rows)}


def print_dry_run(d: dict) -> None:
    t = d["standing"]
    print(f"standing: train {t['train']} ({t['state']})" if t else "standing: no train")
    print("next train" + (" (alone)" if d["alone"] else "") + ": "
          + (", ".join(f"{c['field']} ({c['plan'] or c['branch']}, {c['head'][:12]}"
                       + (f", to resolve in the train: {', '.join(c['conflict'][:5])}" if c.get("conflict") else "")
                       + (f", light checks red, fixed in the train: {c['proof_red'][0]}" if c.get("proof_red") else "")
                       + "".join(f", {k}" for k in ("carried", "gone", "untried", "proof_unknown", "moved_in")
                                 if c.get(k))
                       + ")"
                       for c in d["cars"]) or "none"))  # a conflict rides (plan 0522 D18, resolve.py)
    for c in d.get("riding", []):
        print(f"riding: {c['field']}: in the carrier of train {t['train']} already (a car, never proven again)")
    for r in d.get("barn_red", []):
        print(f"barn red: {r['field']}: the barn's own head shows it too, the barn's fix order first: {r['lines'][0]}")
    for name in ("unhitched", "waiting"):
        for x in d[name]:
            print(f"{name}: {x['field']}: {x['why']}")
    for line in d.get("depends") or []:  # a car behind its dependency, or why none were read (plan 0595 step 12)
        print(f"depends: {line}")
    print("\n".join(yard_report.lines(d["yard"])) or "yard: nothing uncommitted that may ride")
