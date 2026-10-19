"""`tollman.py train --dry-run` (hal2 plan 0294 step 6): the train that stands and trains.py's steps 1 to 4 for
the next one, with what the yard would give it; nothing is written, merged or sent. A train that stands is frozen
(plan 0360 D3): its cars are left out of the next one, a later hitch waits for it."""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import frozen
import leavers
import modes
import mtm_scan
import train_state
import trial as trial_merge
import yard_report
from tick import default_ref
from trains import QUEUE, ROLE, base_of, draft


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
    left = leavers.check(main, str(top), doc.get("queue", []), (doc.get("priority") or {}).get("slots") or [], {},
                         default, dry=True)["held"]  # a ticket that left unmerged: the next train waits for it
    tickets = [t for t in doc.get("queue", []) if t.get("slot") not in rides]
    head = (train or {}).get("base") or (trial_merge.git(str(top), "rev-parse", "HEAD")[1] if top.is_dir() else None)
    d = draft(main, tickets, top.name, base_of(main, default, head), default, modes.of(doc), left)
    return {"field": top.name, "standing": train, **d,
            "yard": yard_report.seen(main, d["base"], default, d["cars"], rows)}


def print_dry_run(d: dict) -> None:
    t = d["standing"]
    print(f"standing: train {t['train']} ({t['state']})" if t else "standing: no train")
    print("next train" + (" (alone)" if d["alone"] else "") + ": "
          + (", ".join(f"{c['field']} ({c['plan'] or c['branch']}, {c['head'][:12]})" for c in d["cars"]) or "none"))
    for name in ("unhitched", "waiting"):
        for x in d[name]:
            print(f"{name}: {x['field']}: {x['why']}")
    print("\n".join(yard_report.lines(d["yard"])) or "yard: nothing uncommitted that may ride")
