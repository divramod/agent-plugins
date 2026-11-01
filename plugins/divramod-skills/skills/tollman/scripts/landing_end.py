"""A red land run ends the landing at once (hal2 plan 0522 step 7, D17): what the 1-minute pass (minute.py) adds to
the watch's events, so a train's red is taken and its fixed carrier pushed in the minute it is due, never at the
round's or the landing's poll. Before it, train 32's run 41167356202 finished red at 05:00:27Z; the red line came
from the round at 05:05:16Z (`trains.settle` runs only on a round, once the landing's process has ended) and the
fixed carrier left at 05:07Z.

The user's three events of a running land run, as the pass's outputs:

1. a red job: its fix order at once (early_order.py, step 6), keyed per job
2. the merge job green: the next train forms once the landing's process has ended (minute.next_train, the chain)
3. the run done: red (`red`): the watch's `workflow finished: failure` of the landing train's current start (the run
   `watch-events.json` keeps closed with its `conclusion`, its merge job not told green) writes the red line at once
   through `train_red.actions`, the round's own path and keys (`red:<train>:<starts>`; the triage, the runner retry,
   the wake), its result made from the red jobs the watch told; the landing's process is never touched (it ends on its
   own: .adr/landings-survive-their-process.md, merge-queue-policy rule 1), the round's settle no longer sees a
   landing train and writes no second red. While the train is `fixing` the pass plans the foremen's `fixed` answers
   (`orders.answers`); once it is `retry` (every fix in: `fixed`, or the session's or a runner's retry) and the last
   start's process is gone, `restart` pushes it with the round's own key (`retry:<train>:<starts>`): one push.
   Green: 2. forms the next train.

Only the pass plans these (a round's trains duty settles, answers and restarts itself). In smuggle mode none.
"""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import train_state
import watch_events

STATUS = "gate_failed"  # what hal2-cli-git's landing says of a red gate run
FAILED = "failure"  # the run's conclusion that ends the landing red (a cancelled run is a pause's or a newer push's)


def told_reds(state: dict) -> list[str]:
    """The red jobs the watch told for its run, in the order it told them."""
    head = f"job:{state.get('run')}:"
    return [k.removeprefix(head) for k in state.get("seen") or [] if k.startswith(head)]


def ended(train: dict | None, state: dict) -> bool:
    """Whether the watched run of `train`'s current start finished red before its merge job was green."""
    rid = str(state.get("run") or "")
    return bool(train) and train["state"] == "landing" and bool(rid) and bool(state.get("closed")) \
        and state.get("conclusion") == FAILED and f"merge:{rid}" not in (state.get("seen") or []) \
        and watch_events.of(state, train)  # this start's run, never the last start's (two can share a second)


def red(top: str, train: dict, state: dict, tickets) -> list[dict]:
    """3. red: the landing's red line and its triage's actions, as the round's settle would plan them."""
    import train_red
    import trains
    names = told_reds(state)
    result = {"status": STATUS, "run": state.get("url"), "red": [{"name": n} for n in names]}
    why = (", ".join(names) or f"the land run {state.get('run')} failed")[:300]
    return train_red.actions(top, train, result, STATUS, why, trains.run, tickets)


def push(top: str, main: str, train: dict) -> list[dict]:
    """The fixed train landed again, once the last start's process is gone (never a second landing beside it)."""
    import hold
    if train_state.alive(train.get("pid")) or hold.of(main):
        return []
    import trains
    return [trains.run("restart", "-", f"retry:{train['train']}:{train['starts']}", "restart", top,
                       text=f"train {train['train']} lands again")]


def actions(top: str, main: str, doc: dict, log: list[dict]) -> list[dict]:
    """The pass's actions for the landing's end (see the module doc); `doc` the queue's (not asleep), `log` the
    role's log (the foremen's acks)."""
    rows = train_state.lines(main)
    train = train_state.standing(rows)
    if not train:
        return []
    if ended(train, state := watch_events.state(main)):
        return red(top, train, state, doc.get("queue", []))
    if train["state"] == "fixing":
        import orders
        return orders.answers(top, rows, log)
    return push(top, main, train) if train["state"] == "retry" else []
