#!/usr/bin/env python3
"""Which tickets may ride and what holds them: the sorting steps of `trains.draft` (hal2 plan 0294 step 6), split
out of trains.py by plan 0383 step 3 (small-files). `trains` re-exports every name, so callers keep `trains.sort_out`."""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import lead_marker
import trial as trial_merge

QUEUE_WATCH = "queue watch"  # who stamps a place leavers.py put back (its reservation's `by`)
HELD = ("the place reserved for field {field} stands in the queue and {field} is not ready: a train's landing waits "
        "behind it (the user's order; `hal2-cli-git worktree queue order`)")


def current_plan(worktree: str) -> str:
    """The first line of the worktree's CURRENT_PLAN (the git dir's, else plans/), or ''."""
    return lead_marker.current_plan(worktree).partition("\n")[0].strip()


def servant(worktree: str | None) -> bool:
    """Whether `worktree` is a servant's: it holds `plans/LEAD`, a foreman's marker (hal2 plan 0383, D16). The field's
    number says nothing: a foreman's wagon from any field 00-99 rides, a marked field never does."""
    return bool(worktree) and lead_marker.pointers.exists(worktree, "LEAD")  # existence only: no process per field


def base_of(main: str, default: str, own: str | None) -> str:
    """What the cars are merged onto: the barn's head, with what the tollman's field holds beyond it (`own`)."""
    if not own or trial_merge.git(main, "merge-base", "--is-ancestor", own, default)[0] == 0:
        return default
    return trial_merge.merge(main, default, own)[0] or default


def sort_out(main: str, default: str, tickets: list[dict], own: str) -> tuple[list[dict], list[dict]]:
    """Steps 1 and 2: the ready tickets that may ride, in queue order, and those that wait ([{field, why, reason}]: a
    servant's field, a head in the barn, a ticket in its own landing, plan 0610 E14). Nothing is unhitched: "when a
    car has hitched, it will never leave the queue again" (the user, 2026-11-04); its ready mark stays, only the user's
    own `--by-user` takes it. A worktree that is gone rides from its hitched sha (E13): the trial and the scratch proof
    need no field."""
    import train_wt  # a round's: leavers.py (the minute's watch) imports this module only for `servant`
    wagons, kept = [], []
    for t in sorted(tickets, key=lambda t: t.get("position", 0)):
        mark, field, with_ = t.get("ready"), t.get("slot"), t.get("rides_with")
        if not mark or field == own or train_wt.is_train(field):
            continue
        if not train_wt.ours(with_, own) or t.get("state", "waiting") != "waiting":  # the head, a leaving one too
            why = f"own landing: it rides with {with_}" if not train_wt.ours(with_, own) else \
                f"own landing: its ticket is {t.get('state')}"
            kept.append({"field": field, "why": why, "reason": "own-landing"})
        elif servant(t.get("worktree")):
            kept.append({"field": field, "why": "a servant's field (plans/LEAD) never rides; it stays hitched",
                         "reason": "servant"})
        elif trial_merge.git(main, "merge-base", "--is-ancestor", mark["head"], default)[0] == 0:
            kept.append({"field": field, "why": "its head is in the barn already; it stays hitched", "reason": "barn"})
        else:
            wagons.append(t)
    return wagons, kept


def held_for(tickets: list[dict], own: str) -> str | None:
    """The field whose reserved place holds the trains back: a waiting ticket the user's order put there, with no
    process of its own and no ready mark (plan 0294 step 12: the carrier's landing waited behind it), standing ahead
    of the first ready ticket in queue order; one behind it holds only the wagons behind it (`held_ahead`, tollman
    learning L95: the carrier takes its first car's place). A leaving ticket in front (held, `waits_for`) holds no
    train back: only a waiter's look frees it, and the hitched have no process, so the carrier's landing has to wait
    behind it."""
    first = next((t for t in _in_order(tickets) if t.get("ready") and t.get("slot") != own), None)
    return held_ahead(tickets, own, first)


def held_ahead(tickets: list[dict], own: str, wagon: dict | None) -> str | None:
    """The field of the first reserved place (as `held_for` says) ahead of `wagon` in queue order (any, for no wagon):
    the user ordered it in first, so `wagon` waits behind it (tollman learning L95). A place the queue watch put back
    (leavers.py) is no user's reservation: it keeps its place and holds no hitched wagon (plan 0610 E18)."""
    end = float("inf") if wagon is None else wagon.get("position", 0)
    for t in _in_order(tickets):
        if t.get("position", 0) >= end:
            return None
        if (t.get("reserved") and not t.get("ready") and not t.get("pid") and t.get("state") == "waiting"
                and t.get("slot") != own and QUEUE_WATCH not in str(t["reserved"].get("by") or "")):
            return t["slot"]
    return None


def _in_order(tickets: list[dict]) -> list[dict]:
    return sorted(tickets, key=lambda t: t.get("position", 0))
