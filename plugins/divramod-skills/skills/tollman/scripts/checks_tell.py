"""The duty `checks`' messages to the sessions (hal2 plan 0306, D4, D5; checks.py has the rules).

Told from the store, one key per entry: `checks-wait:<id>` (a check cancelled and deferred again waits),
`checks-runs:<id>` (a deferred check the duty dispatched runs), `checks-failed:<id>` (a deferral given up after
`checks.TRIES` failed dispatches). A key has a window of SEND_WINDOW, not the frame's week: a send that was refused
(the session busy, a draft) becomes a relay, and that must not block the message for a week. A message goes out
again after the window until the log shows it typed (`do: send`), at most SEND_TRIES times.
"""

import datetime as dt

from tick import act

ROLE = "tollman"
TELL = dt.timedelta(days=1)  # a dispatched or given-up check older than this is not told any more
SEND_WINDOW = dt.timedelta(minutes=30)  # a message not typed (relayed) goes out again after this
SEND_TRIES = 3  # how often one message is planned at most
TEXT = {
    "wait": ROLE + ": your check {title} waits behind the landing ({reason}): the landings have the runners "
                   "first. I dispatch it again after the landing and tell you.",
    "runs": ROLE + ": your check {title} runs: {url}",
    "failed": ROLE + ": your check {title} could not be dispatched: {why}; run ci-check again.",
}


def at(row: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(row["at"].replace("Z", "+00:00"))


def pane_of(entry: dict, panes: dict) -> str | None:
    return panes.get(entry["slot"]) or entry.get("pane")


def untold(key: str, log: list[dict]) -> bool:
    """Not typed into the session yet (a relay may not have reached it) and planned fewer than SEND_TRIES times."""
    done = [e for e in log if e.get("key") == key]
    return not any(e.get("do") == "send" for e in done) and len(done) < SEND_TRIES


def send(s: dict, entry: dict, kind: str, key: str, text: str) -> list[dict]:
    if not untold(key, s.get("log", [])):
        return []
    return [act("checks", kind, "send", entry["slot"], key=key, window=SEND_WINDOW.total_seconds(),
                pane=pane_of(entry, s.get("panes", {})), text=text)]


def waits(s: dict, pending: list[dict], reason: str) -> list[dict]:
    """The sessions whose check the duty cancelled and deferred again: told it waits."""
    out = []
    for e in pending:
        if e.get("again"):
            out += send(s, e, "check-waits", f"checks-wait:{e['id']}",
                        TEXT["wait"].format(title=e.get("title"), reason=reason))
    return out


def told(s: dict, now: dt.datetime, tries: int) -> list[dict]:
    """The sessions whose deferred check the duty dispatched (told it runs) or gave up after `tries` failures."""
    cutoff, out = now.astimezone(dt.timezone.utc) - TELL, []
    titles = {r["id"]: r.get("title") for r in s["rows"] if r["kind"] == "deferred"}
    for e in s["rows"]:
        if at(e) < cutoff:
            continue
        if e["kind"] == "dispatched" and e.get("by") == "checks":
            url = e.get("url") or f"(its run not seen yet: gh run list --workflow <the landing workflow>)"
            out += send(s, e, "check-runs", f"checks-runs:{e['id']}",
                        TEXT["runs"].format(title=e.get("title"), url=url))
        elif e["kind"] == "failed" and (e.get("attempt") or 0) >= tries:
            out += send(s, e, "check-failed", f"checks-failed:{e['id']}",
                        TEXT["failed"].format(title=titles.get(e["id"]), why=e.get("why") or "unknown"))
    return out
