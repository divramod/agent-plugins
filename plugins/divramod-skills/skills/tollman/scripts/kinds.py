#!/usr/bin/env python3
"""Which wagons a train may take (hal2 plan 0375 D8, D19 on plan 0365 D5, D9): a wagon's kind is its entry's effective
mode (`queue_mode.effective`: `effective_mode`, else its own `mode`, else the queue's). Awake, the tollman forms a
train only of adjacent production wagons ("in the beginning he should only form merge trains for official hitches"):

- a hitched smuggle entry is no car: its own `/merge-to-main` smuggles it (the farmer's `lead` tells it, D9);
- a smuggle entry standing in the queue behind a wagon that may ride ends the train there: the production wagons
  after it are not adjacent and wait for the next train, after the smuggler passed alone.
"""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import queue_mode

PRODUCTION, SMUGGLE = queue_mode.PRODUCTION, queue_mode.SMUGGLE


def of(t: dict, mode: dict | None) -> str:
    return SMUGGLE if queue_mode.effective(t, mode or {}) == SMUGGLE else PRODUCTION


def split(tickets: list[dict], own: str, mode: dict | None = None) -> tuple[list[dict], list[dict]]:
    """(the tickets a train may take its cars from, the hitched that wait: [{field, why}]) in queue order. A smuggle
    entry (head and own field aside) behind a hitched production wagon cuts the rest off."""
    rides, waiting, cut = [], [], None
    for t in sorted(tickets, key=lambda t: t.get("position", 0)):
        waits = t.get("state", "waiting") == "waiting" and t.get("slot") != own and not t.get("rides_with")
        if not waits:
            rides.append(t)  # the head, a running car, the tollman's own ticket: sort_out skips or keeps them
        elif of(t, mode) == SMUGGLE:
            if t.get("ready"):
                waiting.append({"field": t["slot"], "why": "its entry's mode is smuggle: it smuggles itself"})
            if cut is None and any(r.get("ready") and r.get("state", "waiting") == "waiting" and r.get("slot") != own
                                   for r in rides):
                cut = t["slot"]
        elif cut and t.get("ready"):
            waiting.append({"field": t["slot"], "why": f"rides in the next train: the smuggler {cut} passes alone "
                                                       "before it, so it is not adjacent"})
        else:
            rides.append(t)
    return rides, waiting
