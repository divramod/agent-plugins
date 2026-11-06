"""The order waiting delegations start in (hal2 plan 0695 row 25, D26).

One order, kept by the delegation ledger (`delegations.jsonl`, written only by delegation.py): the user's own orders
(`user`) first, then the rest oldest first, where `farmer.py delegate --before <key>` puts an entry directly before
the waiting entry `<key>`. A `before` naming nothing waiting is ignored (that entry stays where its age puts it)."""


def order(waiting: list[dict]) -> list[dict]:
    """`waiting` is in the ledger's order (oldest first). Returns the start order: user first, then `before` applied."""
    users = [w for w in waiting if w.get("user")]
    queued = [w for w in waiting if not w.get("user")]
    for w in [w for w in queued if w.get("before")]:
        keys = [q["key"] for q in queued]
        if w["before"] == w["key"] or w["before"] not in keys:
            continue
        queued.remove(w)
        queued.insert([q["key"] for q in queued].index(w["before"]), w)
    return users + queued
