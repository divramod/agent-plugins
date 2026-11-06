#!/usr/bin/env python3
"""The train's lines to the user, computed by code from the facts (hal2 plan 0695 step 10, D19).

The tollman's model never states a train's state from memory or from a watch that can expire: the minute pass prints
these lines at once, each once (its key), and the model relays only them (ROLE.md). The facts: the train state
(`train.jsonl`: `formed`, `started`, `push`), the queue (the pass's own read: mode, hold) and the land run
(`watch-events.json`, written by the pass's watch before these lines are made). With `job failed`, `merge job
green` and `workflow finished` (watch_events.py) a push, a land run start, a red and a green are each one line:

- `train <name> pushed <sha12> at <time>`  key `report:push:<train>:<head12>`: the head a start pushed (kind `push`)
- `land run started: <run> (<link>)`       key `report:run:<run>`: the train's land run, noted by the watch
- `report check: ...`                      the check below, a finding only

`check`: a ready or started train is never reported as waiting. It compares the last state line the log holds for the
train (any line naming it with `waiting`, `waits` or `next round`) with the facts and finds: a formed train ready to
start for more than GRACE minutes, a pushed train with no land run for more than GRACE minutes, and a train line that
says waiting while the facts say started. A finding repeats every FINDING minutes (its key carries the slot).
"""

import train_start
import watch_events
from roletime import age, aware
from tick import act

KIND = "report"
GRACE = 3  # minutes a push may take to show its land run, a ready train to be started by the pass
FINDING = 10  # minutes between two prints of the same finding
WAIT = ("waiting", "waits", "next round")


def pushed(rows: list[dict], train: dict) -> dict | None:
    """The last `push` line of `train`'s current start (after its last `started` line), or None."""
    last = None
    for e in rows:
        if e.get("train") != train["train"]:
            continue
        if e["kind"] == "started":
            last = None
        elif e["kind"] == "push":
            last = e
    return last


def minutes(at, now) -> int | None:
    a = age(at, now)
    return None if a is None else int(a.total_seconds() // 60)


def lines(main: str, rows: list[dict], train: dict | None) -> list[dict]:
    """The push and land-run lines of the standing train, as `record` actions (keyed: once each)."""
    if not train:
        return []
    out, push, s = [], pushed(rows, train), watch_events.state(main)
    if push and push.get("head"):
        out.append(act(KIND, "report-push", "record", "-", key=f"report:push:{train['train']}:{push['head'][:12]}",
                       text=f"train {train['train']} pushed {push['head'][:12]} at {push['at']}"))
    if s.get("run") and s.get("url") and watch_events.of(s, train):
        out.append(act(KIND, "report-run", "record", "-", key=f"report:run:{s['run']}",
                       text=f"land run started: {s['run']} ({s['url']})"))
    return out


def stale(log: list[dict], train: dict) -> dict | None:
    """The last log line naming the train that says it waits, or None."""
    return next((e for e in reversed(log) if train["train"] in str(e.get("text", ""))
                 and any(w in str(e.get("text", "")) for w in WAIT)), None)


def check(main: str, rows: list[dict], train: dict | None, log: list[dict], now, held: dict | None = None,
          asleep: bool = False) -> list[dict]:
    """The findings where the lines and the facts disagree (see the module doc), as `record` actions."""
    if not train:
        return []
    now, name, found = aware(now), train["train"], []
    if train_start.ready(train, held, asleep) and (m := minutes(train.get("at"), now)) is not None and m >= GRACE:
        found.append(f"train {name} is formed and ready, not started after {m} min")
    push = pushed(rows, train)
    s = watch_events.state(main)
    if train["state"] == "landing" and push and not (watch_events.of(s, train) and s.get("run")) \
            and (m := minutes(push.get("at"), now)) is not None and m >= GRACE:
        found.append(f"train {name} pushed {m} min ago, no land run")
    old = stale(log, train)
    if old and train["state"] == "landing" and (older := minutes(old.get("at"), now)) is not None and older >= GRACE:
        found.append(f"the last line of train {name} says waiting ({older} min ago), the facts say {train['state']}")
    return [act(KIND, "report-check", "record", "-", key=f"report:check:{name}:{i}:{now:%Y%m%d%H}:{now.minute // FINDING}",
                text="report check: " + f, window=FINDING * 60) for i, f in enumerate(found)]
