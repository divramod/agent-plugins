#!/usr/bin/env python3
"""The important-interrupt skill's `done` (alias `continue`) and `stats`; interrupt.py is the CLI that calls them.

done: exit 1 when no important interrupt is active (no stop record, or one without its `important_interrupt`
block). Else, in reverse of stop: undo this interrupt's recorded actions (`actions[first_action:]`; an earlier
stop's actions before them stay as they are), newest first, hal2-daemon's SIGCONT last so its VM node starts again
only once the CI runner is back; then tell every session the interrupt told, and still live, to continue (the
replies rechecked: a session that never answered the stop, its message maybe held for its user's approval, is
named); never a session of an earlier hold (D9). Then the record goes to history (stopall.finish); an earlier stop
that was active before the interrupt gets its own record back, so its sessions stay held. A `done` row goes to the
log. --dry-run prints every undo and message and changes nothing.

stats: the log's rows (date, kind, seconds to quiet or to done, frozen, stopped, told, paused, silent), then the
median and the max seconds to quiet of the stops that got quiet; --json prints the same as one object.
"""
import json
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import interrupt
import quiet

CONTINUE_TEXT = (
    "All agents may continue: the important interrupt is over. Run the continue skill now. If your pause record "
    "says a merge to main (an mtm landing) was running, run the merge to main again: it adopts the interrupted "
    "landing; never cancel its run or start it from scratch.")
SIGNALS = ("STOP", "CONT", "TERM")
FROZEN = ("build", "daemon", "session", "docker")


def active(d) -> dict | None:
    path = d.rec.record()
    if not path.exists():
        return None
    state = json.loads(path.read_text())
    return state if isinstance(state.get("important_interrupt"), dict) else None


def kind(a: dict) -> str:
    return a.get("kind") or interrupt.classify(a.get("text", ""))


def undo_order(acts: list) -> list:
    """The actions with an undo, newest first, hal2-daemon last."""
    rev = [a for a in reversed(acts) if a.get("undo")]
    return [a for a in rev if kind(a) != "daemon"] + [a for a in rev if kind(a) == "daemon"]


def perform(step, sys_) -> bool:
    if isinstance(step, tuple):
        pids = step[1] if isinstance(step[1], list) else [step[1]]
        return all([sys_.kill(int(pid), step[0]) for pid in pids])
    return sys_.run(step)[0] == 0


def undo_machine(d, acts: list, dry: bool) -> list:
    """Undo each action (or print it with --dry-run); the kinds of what was undone."""
    kinds = []
    for a in undo_order(acts):
        step = tuple(a["undo"]) if a["undo"][0] in SIGNALS else a["undo"]
        ok = True if dry else perform(step, d.sys)
        d.out(f"{'would undo' if dry else 'undo'} {a['text']}: {quiet.show(step)}{'' if ok else '  (gone or failed)'}")
        if ok:
            kinds.append(kind(a))
    return kinds


def stamp(text: str | None) -> float:
    try:
        return datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError):
        return 0.0


def tell(d, ii: dict, dry: bool) -> list:
    """Tell every session the interrupt told to continue: [{name, status, via, answered}], status delivered,
    dry-run, gone or failed."""
    me = d.msg.self_pid()
    live = {r["name"]: r for r in d.msg.sessions(me if me is not None else -1)}
    paused = {s["name"] for s in ii.get("sessions", []) if s.get("paused")}
    mode, start = d.msg.caller_mode(me), stamp(ii.get("start"))

    def one(name):
        row = live.get(name)
        if row is None:
            return {"name": name, "status": "gone", "via": None, "answered": None}
        answered = name in paused or d.msg.paused_since(row, start)[0]
        res = d.msg.send(row, CONTINUE_TEXT, from_mode=mode, dry_run=dry)
        return {"name": name, "status": res["status"], "via": res["via"], "answered": answered,
                "reason": res.get("reason", "")}

    with ThreadPoolExecutor(max_workers=16) as pool:
        return list(pool.map(one, ii.get("told", [])))


def report(d, res: list, dry: bool) -> None:
    d.out(f"{'session':32} | {'continue':24} | stop answered")
    for r in res:
        answer = "-" if r["answered"] is None else ("yes" if r["answered"] else "no answer")
        d.out(f"{str(r['name'])[:32]:32} | {r['status'] + ' ' + str(r['via'] or ''):24} | {answer}")
        if r["status"] == "failed":
            d.out(f"  not delivered to {r['name']}: {r['reason']}")
    silent = [r["name"] for r in res if r["answered"] is False]
    if silent and not dry:
        d.out("never answered the stop, its messages may wait for approval in its terminal: " + ", ".join(silent))


def close(d, state: dict) -> None:
    """The record to history; an earlier stop's record back in place, with its own actions."""
    ii = state["important_interrupt"]
    d.rec.finish()
    earlier = ii.get("earlier")
    if earlier:
        back = dict(earlier, actions=state.get("actions", [])[:ii.get("first_action", 0)])
        d.rec.record().write_text(json.dumps(back, indent=1) + "\n")
        d.out(f"the earlier stop stays active: {', '.join(earlier.get('stopped', [])) or 'no sessions'}")


def done(a, d) -> int:
    t0, dry = d.clock(), a.dry_run
    state = active(d)
    if state is None:
        d.out("no important interrupt is active: nothing to undo (a stop-all-agent-work stop is undone by "
              "continue-all-agent-work)")
        return 1
    ii = state["important_interrupt"]
    acts = state.get("actions", [])[ii.get("first_action", 0):]
    kinds = undo_machine(d, acts, dry)
    for h in ii.get("held", []):
        d.out(f"left as it is: {h['name']} (earlier hold, {h['why']})")
    res = tell(d, ii, dry)
    report(d, res, dry)
    if dry:
        keep = " (the earlier stop's record stays active)" if ii.get("earlier") else ""
        d.out(f"would close the stop record {d.rec.record()}{keep} and log a done row")
        return 0
    close(d, state)
    secs = d.clock() - t0
    d.out(f"done after {int(secs) // 60}m {int(secs) % 60}s: {len(kinds)} undone, "
          f"{sum(r['status'] == 'delivered' for r in res)} of {len(res)} sessions told to continue")
    interrupt.log(kind="done", start=interrupt.iso(t0), seconds=round(secs, 1),
                  counts={k: kinds.count(k) for k in sorted(set(kinds))}, told=len(res),
                  delivered=sum(r["status"] == "delivered" for r in res),
                  gone=sum(r["status"] == "gone" for r in res), failed=sum(r["status"] == "failed" for r in res),
                  silent=sum(r["answered"] is False for r in res), dry=False, note=state.get("note", ""))
    return 0


def rows(last: int) -> list:
    path = interrupt.root() / "log.jsonl"
    out = []
    for line in path.read_text().splitlines() if path.exists() else []:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out[-last:] if last > 0 else out


def summary(log: list) -> dict:
    quiet_secs = [r["seconds"] for r in log if r.get("kind") == "stop" and r.get("quiet_at")]
    return {"median": statistics.median(quiet_secs) if quiet_secs else None,
            "max": max(quiet_secs) if quiet_secs else None, "quiet_stops": len(quiet_secs)}


def line(r: dict) -> str:
    counts = r.get("counts", {})
    frozen = sum(v for k, v in counts.items() if k in FROZEN)
    stopped = sum(v for k, v in counts.items() if k not in FROZEN)
    secs = f"{r.get('seconds', '-')}" + ("" if r.get("kind") != "stop" or r.get("quiet_at") else " (not quiet)")
    return (f"{str(r.get('start', ''))[:19]:19} | {r.get('kind', '?'):4} | {secs:16} | {frozen:6} | {stopped:7} | "
            f"{r.get('told', 0):4} | {r.get('paused', '-')!s:6} | {r.get('silent', 0)}")


def stats(a, d) -> int:
    log, out = rows(a.last), d.out
    s = summary(log)
    if a.json:
        out(json.dumps({"rows": log, **s}, indent=1))
        return 0
    out(f"{'date':19} | kind | {'seconds':16} | frozen | stopped | told | paused | silent")
    for r in log:
        out(line(r))
    if s["median"] is None:
        out("no stop got quiet yet" if log else f"no runs logged yet ({interrupt.root() / 'log.jsonl'})")
    else:
        out(f"seconds to quiet over {s['quiet_stops']} stops: median {s['median']:.1f}, max {s['max']:.1f}")
    return 0
