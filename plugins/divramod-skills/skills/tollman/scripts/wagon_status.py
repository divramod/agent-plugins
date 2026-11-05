"""A wagon's status, computed from the store's facts and git on every read, never stored.

Pure: git reaches it only through the two callables, so test_wagons.py proves every case.

  entering  an order of this train not answered done (or refused: the tollman must look), or the
            code's resolve stands on this field
  ready     every order answered, but a commit it brought is not in the carrier yet: an answered
            sha, a `need`, the field's `<NN>-train-<n>-<a>-fix` head newer than its order when the done
            named none, or its hitched head (a re-hitch, a rider): it waits for the tollman's merge
  boarded   a car (or a field) with every such commit in the carrier (git's is-ancestor)
  hitched   in the queue, no order, its head not in the carrier
"""


def status(field, fs, *, is_car, queue_head, in_carrier, fix_head, resolving=False):
    """(status, detail). fs: this field's facts of this train, oldest first.

    in_carrier(sha) -> True | False | None (None: the commit is unknown here: never "in").
    fix_head(field) -> (sha, iso time) of the field's fix branch on origin (`<NN>-train-<n>-<a>-fix`, run_names.py), or None.
    """
    closed = {r["id"] for r in fs if r["kind"] == "close"}
    orders = [r for r in fs if r["kind"] == "order" and r["id"] not in closed]
    last = {}
    for r in fs:
        if r["kind"] == "answer":
            last[r["id"]] = r
    open_ids = [o["id"] for o in orders if last.get(o["id"], {}).get("ack") not in ("done",)]
    refused = [i for i in open_ids if last.get(i, {}).get("ack") == "refused"]
    if resolving or open_ids:
        bits = []
        if resolving:
            bits.append("resolving")
        if refused:
            bits.append("refused " + ",".join(refused))
        rest = [i for i in open_ids if i not in refused]
        if rest:
            bits.append(",".join(rest))
        return "entering", " ".join(bits)
    pending = []
    for o in orders:
        a = last.get(o["id"])
        if not a:
            continue
        if a.get("sha"):
            pending.append(a["sha"])
        else:
            fh = fix_head(field)
            if fh and fh[1] >= o["at"]:
                pending.append(fh[0])
    pending += [r["sha"] for r in fs if r["kind"] == "need"]
    worked = bool(orders) or any(r["kind"] == "need" for r in fs)
    if queue_head:
        pending.append(queue_head)
    unmerged = []
    for sha in dict.fromkeys(_dedupe(pending)):
        got = in_carrier(sha)
        if got is not True:
            unmerged.append(sha[:10] + ("?" if got is None else ""))
    if unmerged:
        if is_car or worked:
            return "ready", ",".join(unmerged)
        return "hitched", ""
    if is_car or queue_head:
        return "boarded", ""
    return "hitched", ""


def _dedupe(shas):
    """One entry per commit: a short sha and the full one of the same commit count once."""
    out = []
    for s in shas:
        if not any(o.startswith(s) or s.startswith(o) for o in out):
            out.append(s)
    return out
