"""The farmer's wake (plan 0007 step 6): what a tick hands to the farmer's Claude session, and the waking itself.

A round's items that need the model, `wake` (judgment), `relay` (a templated message for a busy session, sent
verbatim with SendMessage), `notify` (a notice for the user, pushed batched) and the delegations that could not be
placed (`delegate-failed`), go into `wake.json` of the state folder (`roles/farmer/` of the farmer slot):

  {"woken_at": <iso or null>, "items": [{"seq": n, "duty", "kind", "slot", "do", "text", "evidence"?, "brief"?,
                                         "instructions": <the file to read for this kind>}, ...]}

Items accumulate until the session handles them (`farmer.py wake --done <seq>` drops every item up to `seq`). The
session is woken by typing `/farmer act` into its empty prompt (deliver.py) once per batch: a tick with nothing new
adds no turn, a refused wake (the session busy, a draft) is retried by the next tick, and a wake the
session has not acted on within an hour is repeated.

A session whose context reached `CLEAR_AT` percent is woken with `/farmer handoff` instead (hal2's plan 0132): it
writes its handoff.md and starts hal2's clear-and-continue, which types `/clear` and then `/farmer act` itself.
wake.json's `handoff` ({"at", "session"}) holds every other wake back meanwhile; the farmer pane's new session id
ends it (that counts as the wake), and one not done within `HANDOFF_TIMEOUT` falls back to a plain `/clear` and
`/farmer act`.
"""

import datetime as dt
import json
import time
from pathlib import Path

import deliver
import mtm_scan

SKILL = Path(__file__).resolve().parents[1]
KINDS = ("wake", "relay", "notify")
SUBSKILLS = {"mtm": "merge-to-main-boss", "lead": "development-lead", "ci": "ci", "watch": "sanity-watch",
             "autoclear": "fix-autoclear", "trains": "merge-train"}
ACT = "/farmer act"
HANDOFF = "/farmer handoff"
CLEAR_AT = 40  # context percent from which a wake asks for the handoff and its clear: a call re-reads the context
HANDOFF_TIMEOUT = dt.timedelta(minutes=15)  # a handoff not done by then falls back to a plain /clear
CLEARED = 60  # seconds to wait for the cleared session
REWAKE = dt.timedelta(hours=1)  # a wake the session never acted on is repeated


def wake_file(main: str) -> Path:
    return mtm_scan.state_dir(main) / "wake.json"


def instructions(duty: str, kind: str) -> str:
    """The one file the woken session reads for an item: `instructions/<duty>.<kind>.md`, else
    `instructions/<duty>.md`, else its duty's subskill, else SKILL.md."""
    for own in (SKILL / "instructions" / f"{duty}.{kind}.md", SKILL / "instructions" / f"{duty}.md",
                SKILL / "subskills" / SUBSKILLS.get(duty, "-") / "SUBSKILL.md"):
        if own.exists():
            return str(own)
    return str(SKILL / "SKILL.md")


def items(out: dict) -> list[dict]:
    """The round's items for the model: wake, relay and notify actions, and delegations that failed."""
    found = [a for k in KINDS for a in out.get(k, [])]
    found += [{"duty": "farmer", "kind": "delegate-failed", "slot": d.get("slot") or "-", "do": "wake",
               "text": f"delegation failed: {d.get('title') or d.get('key')}", "evidence": d}
              for d in out.get("delegations", []) if d.get("state") == "error"]
    keep = ("duty", "kind", "slot", "do", "text", "evidence", "brief", "why", "key")
    return [{**{k: a[k] for k in keep if k in a}, "instructions": instructions(a["duty"], a["kind"])} for a in found]


def read(main: str) -> dict:
    f = wake_file(main)
    try:
        return json.loads(f.read_text()) if f.exists() else {"woken_at": None, "items": []}
    except json.JSONDecodeError:
        return {"woken_at": None, "items": []}


def write(main: str, data: dict) -> None:
    f = wake_file(main)
    if not data["items"]:
        f.unlink(missing_ok=True)
        return
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str) + "\n")
    tmp.replace(f)


def farmer_pane(top: str) -> str | None:
    """The pane of the agent whose checkout is the farmer slot."""
    code, text = deliver.cli("list", "--json")
    try:
        data = json.loads(text) if code == 0 else []
    except json.JSONDecodeError:
        return None
    rows = data.get("list", []) if isinstance(data, dict) else data
    target = Path(top).resolve()
    return next((a.get("pane_id") for a in rows
                 if a.get("checkout") and Path(a["checkout"]).resolve() == target), None)


def plain_clear(pane: str, before: dict, sleep=time.sleep) -> str | None:
    """Type `/clear` and wait for the new session (the fallback when a handoff never finished). None when it is
    ready for the wake, else why not."""
    why = deliver.send(pane, "/clear")
    if why:
        return f"/clear not typed: {why}"
    for _ in range(CLEARED // 2):
        sleep(2)
        b = deliver.agent(pane) or {}
        if b.get("session_id") != before.get("session_id") and b.get("state") in deliver.READY:
            return None
    return "the cleared session did not come back"


def log_wake(main: str, kind: str, what: str) -> None:
    mtm_scan.log(main, {"kind": kind, "slot": "farmer", "what": what, "note": "", "by": "tick", "do": "wake"})


def pending_handoff(pane: str, main: str, data: dict, now: dt.datetime, sleep=time.sleep) -> tuple[str | None, bool]:
    """A handoff under way: (why no wake now, woken). Its new session counts as the wake (the clear-and-continue
    job typed /farmer act); past HANDOFF_TIMEOUT the plain /clear and /farmer act."""
    pending, a = data["handoff"], deliver.agent(pane) or {}
    if a.get("session_id") and a["session_id"] != pending.get("session"):
        del data["handoff"]
        log_wake(main, "handoff-done", f"handed off: session {a['session_id']} got {ACT}")
        return None, True
    if now - dt.datetime.fromisoformat(pending["at"]) < HANDOFF_TIMEOUT:
        return "handoff under way", False
    del data["handoff"]
    log_wake(main, "handoff-timeout", f"no handoff since {pending['at']}: plain /clear, then {ACT}")
    why = plain_clear(pane, a, sleep) or deliver.send(pane, ACT)
    return why, not why


def wake_session(pane: str, main: str, data: dict, now: dt.datetime, sleep=time.sleep) -> tuple[str | None, bool]:
    """Wake the farmer session: (why not, woken). A large context gets the handoff request instead of the wake."""
    if data.get("handoff"):
        return pending_handoff(pane, main, data, now, sleep)
    a = deliver.agent(pane) or {}
    if (a.get("context_percent") or 0) < CLEAR_AT:
        why = deliver.send(pane, ACT)
        return why, not why
    why = deliver.send(pane, HANDOFF)
    if not why:
        data["handoff"] = {"at": now.isoformat(timespec="seconds"), "session": a.get("session_id")}
        log_wake(main, "handoff", f"{HANDOFF}: context {a.get('context_percent')}%")
    return why or "handoff asked", False


def hand_over(top: str, main: str, out: dict, now: dt.datetime) -> dict:
    """Add the round's items to wake.json and wake the farmer session when it holds a batch it was not woken for.
    Returns {"items": n new, "pending": n in the file, "woken": bool, "why": refusal}."""
    data, new = read(main), items(out)
    seq = max((i["seq"] for i in data["items"]), default=0)
    for i in new:
        seq += 1
        data["items"].append({"seq": seq, **i})
    if new:
        data["woken_at"] = data.get("woken_at") if data["items"][:-len(new)] else None
    result = {"items": len(new), "pending": len(data["items"]), "woken": False}
    stale = data.get("woken_at") and now - dt.datetime.fromisoformat(data["woken_at"]) > REWAKE
    if data["items"] and (not data.get("woken_at") or stale or data.get("handoff")):
        pane = farmer_pane(top)
        why, woken = wake_session(pane, main, data, now) if pane else ("no farmer session", False)
        if why:
            result["why"] = why
        if woken:
            data["woken_at"], result["woken"] = now.isoformat(timespec="seconds"), True
            log_wake(main, "wake", f"{ACT}: {len(data['items'])} items")
    write(main, data)
    return result


def done(main: str, upto: int) -> int:
    """Drop the items the woken session handled (seq ≤ upto); a later batch is woken for by the next tick.
    Returns the items left."""
    data = read(main)
    data["items"] = [i for i in data["items"] if i["seq"] > upto]
    data["woken_at"] = None
    data.pop("handoff", None)
    write(main, data)
    return len(data["items"])
