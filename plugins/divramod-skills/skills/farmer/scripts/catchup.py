"""Safe catch-up (hal2 plan 0530 D6): after a long outage a round never acts on an old item.

An action of the round (tick.py) may carry `born`, the time of the item it comes from (an incident's, an ack's): a
stamp, a datetime or an epoch in seconds or milliseconds. A send, relay, wake or notify whose item is older than the
action's `window` (else STALE_AFTER) is turned into one `stale-skip` record under the same key, kept STALE_KEEP, so
`tick.fresh` logs it once and never plans it again; the acts `after` it are dropped. An action without `born` is
never stale.
"""

import datetime as dt

import roletime

STALE_AFTER = 24 * 3600  # an item older than its action's window, else this, is not acted on (plan 0530 D6)
STALE_KEEP = 365 * 24 * 3600  # a stale-skip line holds its key this long: logged once
TALKS = ("send", "relay", "wake", "notify")


def item_time(value) -> dt.datetime | None:
    """An item's own time as aware UTC: a state stamp (roletime.parse), a datetime (naive = local) or an epoch in
    seconds or milliseconds (sanity-watch's incidents); None when it is none of them."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return dt.datetime.fromtimestamp(value / 1000 if value > 1e11 else value, dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return roletime.aware(value) if isinstance(value, (str, dt.datetime)) else None


def stale(actions: list[dict], now: dt.datetime) -> list[dict]:
    """The actions with every send, relay, wake and notify whose item (`born`) is older than its window turned into
    one `stale-skip` record under the same key (kept STALE_KEEP, so `fresh` logs it once), and the acts `after` it
    gone. `now` naive (local) or aware."""
    now, gone, out = roletime.aware(now), set(), []
    for a in actions:
        if a.get("after") and a["after"] in gone:
            continue
        born = item_time(a.get("born")) if a["do"] in TALKS else None
        if born is None or (now - born).total_seconds() < a.get("window", STALE_AFTER):
            out.append(a)
            continue
        key, hours = a.get("key") or f"stale:{a['duty']}:{a['kind']}:{a['slot']}:{roletime.stamp(born)}", \
            int((now - born).total_seconds() // 3600)
        gone.add(key)
        out.append({"duty": a["duty"], "kind": "stale-skip", "slot": a["slot"], "do": "record", "key": key,
                    "window": STALE_KEEP, "text": f"not done ({a['do']} {a['kind']}): its item is {hours} h old "
                                                  f"({roletime.stamp(born)}), past its window; key {key}"})
    return out
