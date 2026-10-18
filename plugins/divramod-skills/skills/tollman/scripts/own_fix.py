"""The barn's fix with no train standing (hal2 plan 0360 step 8, D29): `tollman.py order main` while no train stands
orders the tollman's own hand, and the fix becomes the first car of the next train.

- `order`: an `order` line without `train` (field `main`, branch `tollman-train-fix`, `base` the field's head), one
  `fix-order-main` wake for the own session: the hand branches from the base, fixes, commits, switches back to the
  field's own branch, then runs `tollman.py fixed main <sha>`. One such order at a time.
- `fixed`: the answer checked as orders.check does (the local branch counts) and merged into the field's own
  branch (orders.merge), a `fixed` line without `train`.
- How it rides: the next draft is made on `trains.base_of(main, default, <the field's head>)`, the barn with what the
  field holds beyond it, and `engine.form` merges the cars onto that head: the fix's merge lies under every car, the
  first car of the next train. Until the fix is merged no train forms (trains.plan waits on `waiting`), so no train
  leaves without it and none forms while the hand works on the side branch.
- `waiting`: the open or merged own fix not yet in the barn (a `landed` line after its `fixed` ends it).
  `carries` (the frame's roles.Wiring.carries) is true while it waits, as while a train stands: the field holds
  more than its role file by design, so the round neither stops on it nor merges from main.
"""

from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import orders
import train_state
from carrier import git
from tick import act

TEXT = {
    "order": "tollman (wagon train): fix order {id}: the barn is red ({why}). Run: {run}. No train stands: a hand of "
             "yours fixes it in the tollman's field on `{branch}` from {base} (`git switch -C {branch} {base}`), "
             "commits, switches back to `{carrier}`, then you run `tollman.py fixed main <sha>`: the fix is the first "
             "car of the next train, which waits for it.",
}


def waiting(rows: list[dict]) -> dict | None:
    """The own fix order made with no train standing and not yet in the barn: {id, branch, base, why, run, sha}
    (`sha` None while open), or None."""
    own = None
    for e in rows:
        kind = e["kind"]
        if kind == "order" and e.get("field") == orders.MAIN and not e.get("train"):
            own = {k: e.get(k) for k in ("id", "field", "branch", "base", "why", "run", "at")} | {"sha": None}
        elif own and kind == "fixed" and not e.get("train") and e.get("id") == own["id"]:
            own.update(sha=e.get("sha"), commit=e.get("commit"))
        elif own and own["sha"] and kind == "landed":
            own = None
    return own


def carries(top: str) -> bool:
    """The frame's question (roles.Wiring.carries): a train stands, or the own fix waits to ride."""
    return train_state.carries(top) or waiting(train_state.lines(mtm_scan.main_checkout(top))) is not None


def order(top: str, why: str, run: str | None, now=None) -> tuple[int, str, list[dict]]:
    """`order main` with no train standing: its exit, its line and the own session's wake."""
    main = mtm_scan.main_checkout(top)
    rows = train_state.lines(main)
    if w := waiting(rows):
        state = "merged and waits to ride" if w["sha"] else "open"
        return 1, f"fix order {w['id']} for the barn is {state}: no second one", []
    base, carrier = git(top, "rev-parse", "HEAD")[1], Path(top).name
    oid = orders.next_id(rows, orders.MAIN)
    train_state.append(main, "order", carrier, now, field=orders.MAIN, branch=orders.OWN_FIX, base=base, why=why,
                       run=run, id=oid)
    words = {"id": oid, "why": why, "run": run or "none", "branch": orders.OWN_FIX, "base": base[:12],
             "carrier": carrier}
    a = act("trains", "fix-order-main", "wake", key=f"order:next:{oid}", text=TEXT["order"].format(**words),
            evidence=words)
    return 0, f"fix order {oid}: the tollman's hand fixes the barn on {orders.OWN_FIX} from {base[:12]}", [a]


def fixed(top: str, sha: str, now=None) -> tuple[int, str, list[dict]]:
    """The answer to the open own order: merged into the field's own branch, or refused (the order stays open)."""
    main = mtm_scan.main_checkout(top)
    o = waiting(train_state.lines(main))
    if not o or o["sha"]:
        return 1, "no open fix order for main", []
    own, branch = Path(top).name, git(top, "branch", "--show-current")[1]
    why = f"the field is on {branch or 'no branch'}: switch back to {own} first" if branch != own else \
        orders.check(top, o, sha)
    code, commit = (1, why) if why else orders.merge(top, o, sha)
    if code:
        return 1, f"fix order {o['id']} stays open: {commit}", []
    train_state.append(main, "fixed", own, now, field=orders.MAIN, id=o["id"], sha=sha, commit=commit)
    return 0, f"fix order {o['id']} merged ({sha[:12]}): the first car of the next train", []
