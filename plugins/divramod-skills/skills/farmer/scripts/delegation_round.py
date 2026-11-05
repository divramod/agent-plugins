"""One round's follow-up of the running delegations (hal2 plan 0618): the facts gathered once a round, never per
entry (one `git grep` of the plan statuses on origin/main, one `hal2-cli-git worktree transplants --json`, the fields
the tick listed with each plan's `created`), each running entry judged by delegation_sync.reconcile, and its verdict
applied: a terminal state (`landed`, `gone`, `moved`) written once to the ledger with one journal line, so it is
logged once by construction (D4); only the entry's own landing stops its session when idle; a transplant follows its
field; a still running entry gets its field's plan recorded once (`plan`), so later rounds compare exactly (D3).

delegation.py is imported late: it imports this module, and its `call` is the one seam the tests mock.
"""

import datetime as dt
import re
from pathlib import Path

import delegation_sync as sync
import field_pause
import live_sessions
import mtm_scan
import transplants

STATUS = re.compile(r"^[^:]+:(?P<path>plans/.+/plan\.md):status:\s*(?P<status>\S+)")
CREATED = re.compile(r"^created:\s*(\d{4}-\d{2}-\d{2})", re.M)
WHAT = {"landed": "the foreman's plan has landed", "gone": "the foreman's field is gone",
        "moved": "the foreman's field holds another plan"}


def main_plans(main: str, call) -> dict[str, str]:
    """Every plan's status on origin/main, by its folder name, in one `git grep`; {} when git fails."""
    code, out = call(["git", "grep", "-e", "^status:", "origin/main", "--", "plans/*/plan.md"], main)
    found = {}
    for line in out.splitlines() if code == 0 else []:
        if m := STATUS.match(line):
            found.setdefault(Path(m["path"]).parent.name, m["status"].strip("\"'"))
    return found


def created(path: str | None, plan: str | None) -> str:
    """The `created:` day of the field's plan (`<field>/plans/<plan>/plan.md`), "" when unknown."""
    slug = sync.plan_slug(plan)
    if not (path and slug):
        return ""
    try:
        head = (Path(path) / "plans" / slug / "plan.md").read_text()[:4000]
    except OSError:
        return ""
    m = CREATED.search(head)
    return m.group(1) if m else ""


def gather(main: str, slots: dict[str, dict], lines: list[dict], call) -> dict:
    """The round's facts. `slots`: field → {plan, ahead, [path]} (tick.slot_state); an empty one means the field
    list is unknown, so no entry is judged gone."""
    fields = {s: {**v, "created": created(v.get("path"), v.get("plan"))} for s, v in slots.items()}
    return {"fields": fields, "known": bool(slots), "main": main_plans(main, call),
            "transplants": transplants.history(main, call), "starts": sync.starts(lines)}


def running_entries(main: str) -> dict[str, dict]:
    """The ledger's running entries that name a field, by key."""
    import delegation
    return {k: e for k, e in delegation.ledger(main).items() if e.get("state") == "running" and e.get("slot")}


def judge(main: str, slots: dict[str, dict], now: dt.datetime, running: dict[str, dict]) -> list[tuple[str, dict, dict | None]]:
    """The verdict on every running entry, in ledger order (None: no readable start, left as it is). The facts are
    gathered once; nothing is written. The tick and `delegation.py reconcile` both read the round through this."""
    import delegation
    if not running:
        return []
    facts = gather(main, slots, delegation.lines(main), delegation.call)
    return [(k, e, None if (f := sync.entry_facts(k, e, facts)) is None else sync.reconcile(e, f, now))
            for k, e in running.items()]


def follow_up(main: str, slots: dict[str, dict], dry: bool, now: dt.datetime) -> list[dict]:
    """Reconcile every running entry; returns the changed ones (terminal or transplanted), in ledger order."""
    out = []
    for key, _, v in judge(main, slots, now, running_entries(main)):
        if v is not None:
            out += settle(main, key, v, dry, now)
    return out


def settle(main: str, key: str, v: dict, dry: bool, now: dt.datetime) -> list[dict]:
    """Apply one verdict: nothing in a dry round; returns it unless the entry simply runs on."""
    import delegation
    if v["state"] == "running" and not v.get("from"):
        if v.get("plan") and not dry:
            delegation.note(main, {"key": key, "state": "running", "slot": v["slot"], "plan": v["plan"]}, now)
        return []
    d = {"key": key, **{k: v[k] for k in ("state", "slot", "from", "reason") if v.get(k)}}
    if v.get("stop"):
        d["stop"] = delegation.STOP + [v["slot"], "--repo", main]
    if dry:
        return [d]
    if d.get("stop"):
        delegation.call(d["stop"], main)  # refuses a busy session: then it stays, nothing lost
    delegation.note(main, {k: x for k, x in d.items() if k != "stop"}, now)
    if d.get("from"):  # the delegation follows its field: running in the target, its session left alone
        mtm_scan.log(main, {"kind": "transplant", "slot": d["slot"], "by": "tick", "key": key,
                            "what": f"the servant's field moved from {d['from']}",
                            "note": "still running; the delegation follows the target"})
    else:
        mtm_scan.log(main, {"kind": d["state"], "slot": d["slot"], "what": WHAT[d["state"]], "by": "tick", "key": key,
                            "note": d["reason"] + ("; session stopped when idle" if d.get("stop") else "")})
    return [d]


def capacity(main: str, slots: dict[str, dict], limit: int | str) -> int | None:
    """How many running foremen use capacity (D6): the running entries of the ledger whose field is unpaused and
    holds a live session; the session list and the pauses are read once, here. None for `auto`, whose room is the
    machine's load, not a count (nothing is read then)."""
    import delegation
    if limit == "auto":
        return None
    running = [e for e in delegation.ledger(main).values() if e.get("state") == "running"]
    return len(sync.working(running, working_facts(main, slots))) if running else 0


def working_facts(main: str, slots: dict[str, dict]) -> dict:
    """What `sync.working` reads, gathered once: the session list (None when unreadable), the pauses, each field's path."""
    return {"sessions": live_sessions.read(), "paused": field_pause.load(main),
            "paths": {s: v.get("path") for s, v in slots.items()}}


def place(main: str, slots: dict[str, dict], limit: int | str, dry: bool, now: dt.datetime, values: dict | None) -> list[dict]:
    """Start the waiting briefs while there is room, counting only the working foremen (D6); `auto`: one a round.
    Returns each delegation's result."""
    import delegation
    waiting = [{"key": k, "text": e["title"], "brief": {"brief_file": e["brief"]}, "duty": "farmer",
                "kind": "waiting", "slot": "-", **{f: e[f] for f in ("prompt", "role_task") if e.get(f)}}
               for k, e in delegation.ledger(main).items() if e.get("state") == "waiting"]
    busy = capacity(main, slots, limit) if waiting else None
    room = int(delegation.has_room(limit, 0)) if busy is None else limit - busy
    out = []
    for w in waiting[:max(room, 0)]:
        out.append(delegation.delegate(w, main, limit, dry, now, values, busy=busy))
        busy = busy + (out[-1].get("state") == "running") if busy is not None else None
    return out
