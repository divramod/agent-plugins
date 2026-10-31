"""What the farmer's log says about the worktrees (hal2 plan 0137, split from tick.py): the log read tolerantly, the
worktrees with an open question to the user, the worktrees the boss paused."""

import datetime as dt

import mtm_scan


def read_log(main: str, role: str = mtm_scan.roles.ROLE) -> list[dict]:
    return mtm_scan.entries(mtm_scan.state_dir(main, role) / "log.jsonl")


ANSWERS = ("answered", "answer", "decision")  # log kinds that close a worktree's open `ask` (plan 0137)


def waiting_for_user(log: list[dict]) -> set[str]:
    """Worktrees with an open question to the user: their last `ask` or answer (`answered`, `answer`, `decision`) log
    entry is an `ask`."""
    state: dict[str, str] = {}
    for e in log:
        if e.get("kind") in ("ask",) + ANSWERS:
            for slot in str(e.get("slot", "")).split(","):
                state[slot.strip()] = e["kind"]
    return {s for s, k in state.items() if k == "ask"}


PAUSE_AGE = dt.timedelta(hours=12)


def paused(log: list[dict], now: dt.datetime) -> set[str]:
    """Worktrees the boss paused for a landing (a `pause:<landing>:<slot>` key in the last 12 h) with no go after it."""
    out: dict[str, bool] = {}
    for e in log:
        kind, _, rest = e.get("key", "").partition(":")
        if kind in ("pause", "go") and mtm_scan.log_time(e["at"]) >= now - PAUSE_AGE:
            out[rest.rsplit(":", 1)[-1]] = kind == "pause"
    return {slot for slot, on in out.items() if on}


def paused_by_any_boss(main: str, now: dt.datetime) -> set[str]:
    """The worktrees paused by the merge-to-main boss, whose log is the tollman's (the farmer's before plan 0294).
    The tollman's folder is only read here, never created."""
    roles = mtm_scan.roles
    if mtm_scan.DATA is not None:
        path = mtm_scan.DATA / roles.main_checkout(main).name / "tollman" / "log.jsonl"
    else:
        path = roles.slot_dir(main, "tollman") / "roles" / "tollman" / "log.jsonl"
    return paused(read_log(main), now) | paused(mtm_scan.entries(path), now)
