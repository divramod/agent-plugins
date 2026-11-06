#!/usr/bin/env python3
"""The start of a formed train, one test for the round and the minute pass (hal2 plan 0695 step 9, D10).

A train formed and never started (state `formed`) starts when its hold is lifted and the tollman is awake (not smuggle
mode): `ready`. Nothing else can be landing then: a landing's train is `landing`, not `formed`. `actions` is what the
round's trains duty (`trains.plan`) and the minute pass (`minute.started`) both plan: the open train's joins, then the
`restart` run under the round's key (`resume:<train>`, `train_state.restart_key`), so whichever runs first starts it
and the other's `tick.fresh` drops it; a ten-minute round never delays a ready train.
"""

import train_state


def ready(train: dict | None, held: dict | None, asleep: bool) -> bool:
    """Whether `train` is formed, never started, with no hold and the tollman awake."""
    return bool(train) and train["state"] == "formed" and not held and not asleep


def restart(top: str, train: dict) -> dict:
    """The `restart` run action of a formed train (its key and window as the round's)."""
    import trains
    return trains.run("restart", "-", train_state.restart_key(train), "restart", top,
                      text=f"train {train['train']} lands again", window=trains.RESUME_WINDOW)


def actions(top: str, main: str, train: dict | None, tickets: list[dict], mode: dict | None,
            held: dict | None = None, asleep: bool = False) -> list[dict]:
    """The joins and the restart of a ready train, else []."""
    if not ready(train, held, asleep):
        return []
    import trains
    return trains.join_actions(top, main, train, tickets, mode) + [restart(top, train)]
