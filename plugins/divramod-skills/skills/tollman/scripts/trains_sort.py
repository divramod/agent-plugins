#!/usr/bin/env python3
"""Which tickets may ride and what holds them: the sorting steps of `trains.draft` (hal2 plan 0294 step 6), split
out of trains.py by plan 0383 step 3 (small-files). `trains` re-exports every name, so callers keep `trains.sort_out`."""

from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import lead_marker
import train_wt
import trial as trial_merge

HELD = ("the place reserved for field {field} stands in the queue and {field} is not ready: a train's landing waits "
        "behind it (the user's order; `hal2-cli-git worktree queue order`)")
HELD_LEFT = ("the place of field {field} in the queue ended unmerged or was stopped: it stays (a queued place is never "
             "given up) and a train waits behind it until {field} is back in motion (plan 0383 step 3)")


def current_plan(worktree: str) -> str:
    """The first line of the worktree's CURRENT_PLAN (the git dir's, else plans/), or ''."""
    return lead_marker.current_plan(worktree).partition("\n")[0].strip()


def servant(worktree: str | None) -> bool:
    """Whether `worktree` is a servant's: it holds `plans/LEAD`, a foreman's marker (hal2 plan 0383, D16). The field's
    number says nothing: a foreman's wagon from any field 00-99 rides, a marked field never does."""
    return bool(worktree) and lead_marker.marker(worktree) is not None


def base_of(main: str, default: str, own: str | None) -> str:
    """What the cars are merged onto: the barn's head, with what the tollman's field holds beyond it (`own`)."""
    if not own or trial_merge.git(main, "merge-base", "--is-ancestor", own, default)[0] == 0:
        return default
    return trial_merge.merge(main, default, own)[0] or default


def sort_out(main: str, default: str, tickets: list[dict], own: str) -> tuple[list[dict], list[dict]]:
    """Steps 1 and 2: the ready tickets that may ride, in queue order, and those unhitched at once."""
    wagons, unhitched = [], []
    for t in sorted(tickets, key=lambda t: t.get("position", 0)):
        mark, field = t.get("ready"), t.get("slot")
        if not mark or field == own or not train_wt.ours(t.get("rides_with"), own) or t.get("state", "waiting") != "waiting":
            continue  # also a ticket at the head, a leaving one included (`waits_for`): its own landing's, no car
        gone = {"field": field, "head": mark["head"], "at": mark.get("at", ""), "tell": None}
        if servant(t.get("worktree")):
            unhitched.append({**gone, "why": "a servant's field (plans/LEAD) never rides", "tell": "servant"})
        elif not Path(t.get("worktree") or "-").is_dir():
            unhitched.append({**gone, "why": "its worktree is gone"})
        elif trial_merge.git(main, "merge-base", "--is-ancestor", mark["head"], default)[0] == 0:
            unhitched.append({**gone, "why": "its head is in the barn already"})
        else:
            wagons.append(t)
    return wagons, unhitched


def held_for(tickets: list[dict], own: str) -> str | None:
    """The field whose reserved place holds every train back: a waiting ticket the user's order put there, with no
    process of its own and no ready mark (plan 0294 step 12: the carrier's landing waited behind it). A leaving
    ticket in front (held, `waits_for`) holds no train back: only a waiter's look frees it, and the hitched have
    no process, so the carrier's landing has to wait behind it."""
    return next((t["slot"] for t in tickets if t.get("reserved") and not t.get("ready") and not t.get("pid")
                 and t.get("state") == "waiting" and t.get("slot") != own), None)
