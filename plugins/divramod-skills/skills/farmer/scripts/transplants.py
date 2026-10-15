"""Where a field's work went (hal2 plan 0286, D26). The farmer's delegations ledger names a servant's field (`slot`)
and no plan, so after `/transplant` moved the foreman to another field the old field looks like a landed one: no
plan, no commits ahead. `moved` follows the transplants hal2-git recorded (`hal2-cli-git worktree transplants
--json`) from the entry's field to the field its foreman works in now; `delegation.follow_up` keeps such an entry
`running` there, and its session is not stopped.

Only a transplant that reached `driven` or `arrived` moved the work; a `prepared` or `cancelled` one moved nothing. A
transplant older than the entry is no business of it: the entry was written after the work had moved already.
"""

import datetime as dt
import json

MOVED = ("driven", "arrived")


def when(text) -> dt.datetime | None:
    """An RFC 3339 time of a record, as an aware datetime; None when it is missing or unreadable."""
    try:
        return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def history(main: str, call=None) -> list[dict]:
    """The repository's transplants, newest first as the CLI prints them. An installed CLI without the command, a
    failure or output that is not the contract answers [] (nothing moved): the farmer never fails on it.
    `call` is `delegation.call` (the one seam the tests mock)."""
    if call is None:
        import delegation  # late: delegation imports this module
        call = delegation.call
    code, out = call(["hal2-cli-git", "worktree", "transplants", "--json"], main)
    try:
        found = json.loads(out).get("transplants") if code == 0 else None
    except (json.JSONDecodeError, AttributeError):
        return []
    return [t for t in found if isinstance(t, dict)] if isinstance(found, list) else []


def follow(records: list[dict], slot: str, since: dt.datetime) -> tuple[str | None, str]:
    """Follow the chain from `slot`: the earliest moving transplant from it driven after `since`, then the next one
    from its target after that. Returns (the field the work is in now, or None when it never moved; the last hop's
    record id for the log). A round trip back to `slot` is a move too."""
    here, at, last, hopped = slot, since.astimezone(), "", False
    for _ in range(len(records)):
        hops = sorted(((w, t) for w, t in ((when(t.get("driven")), t) for t in records
                                           if t.get("state") in MOVED and t.get("from") == here and t.get("to"))
                       if w and w > at), key=lambda x: x[0])
        if not hops:
            break
        at, t = hops[0]
        here, last, hopped = t["to"], str(t.get("id") or ""), True
    return (here if hopped else None), last


def moved(main: str, slot: str, since: dt.datetime, call=None) -> str | None:
    """The field `slot`'s foreman works in now, if a transplant moved it after `since`; else None."""
    return follow(history(main, call), slot, since)[0]
