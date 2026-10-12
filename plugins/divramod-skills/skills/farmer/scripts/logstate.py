"""What the farmer's log says about the slots (hal2 plan 0137, split from tick.py): the log read tolerantly, the
slots with an open question to the user, the slots the boss paused."""

import datetime as dt

import mtm_scan


def read_log(main: str) -> list[dict]:
    return mtm_scan.entries(mtm_scan.state_dir(main) / "log.jsonl")


ANSWERS = ("answered", "answer", "decision")  # log kinds that close a slot's open `ask` (plan 0137)


def waiting_for_user(log: list[dict]) -> set[str]:
    """Slots with an open question to the user: their last `ask` or answer (`answered`, `answer`, `decision`) log
    entry is an `ask`."""
    state: dict[str, str] = {}
    for e in log:
        if e.get("kind") in ("ask",) + ANSWERS:
            for slot in str(e.get("slot", "")).split(","):
                state[slot.strip()] = e["kind"]
    return {s for s, k in state.items() if k == "ask"}


PAUSE_AGE = dt.timedelta(hours=12)


def paused(log: list[dict], now: dt.datetime) -> set[str]:
    """Slots the boss paused for a landing (a `pause:<landing>:<slot>` key in the last 12 h) with no go after it."""
    out: dict[str, bool] = {}
    for e in log:
        kind, _, rest = e.get("key", "").partition(":")
        if kind in ("pause", "go") and dt.datetime.fromisoformat(e["at"]) >= now - PAUSE_AGE:
            out[rest.rsplit(":", 1)[-1]] = kind == "pause"
    return {slot for slot, on in out.items() if on}
