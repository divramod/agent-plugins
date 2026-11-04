#!/usr/bin/env python3
"""The important-interrupt skill's one call: quiet the whole Mac now, measure how long it took, undo it later.

Usage: interrupt.py [stop] [--dry-run] [--idle 80] [--timeout 300] [--reply-wait 90] [--note TEXT]
       interrupt.py done|continue [--dry-run]       (resume.py: undo it, tell the sessions to continue)
       interrupt.py stats [--json] [--last N]       (resume.py: the log's rows, median and max to quiet)

stop, in this order: the stop record (stop-all-agent-work's stopall.py, "kind": "important-interrupt"; a session in
an active stop or with an older pause record is an earlier hold and is left as it is); every other live session of
the machine told to pause (source 5, the farmers of other farms among them; messenger.py, Claude Code's inbox socket,
else hal2-cli-agents send); hal2-daemon's pollers held (source 3, pollers_quiet.py: `hal2-cli-machine quiet hold pollers`, its release recorded;
without the CLI hal2-daemon frozen), every tart VM stopped (source 2); the workqueue's `freeze
all` and its holders (source 1, sources.py); every repo's host runners (source 4, runners.py); quiet.py apply with
every CONFIRM row confirmed (no safety question); every build and test process frozen (freeze.py); the workqueue's
quiet mode on (wq_quiet.py); then every 5 s a re-scan freezes what is new, until the CPU is at least --idle % idle
and nothing was new, or --timeout seconds passed; then the replies (a newer pause record or an idle state) until
--reply-wait seconds after the start. Each pass is measured (seconds, CPU idle after: passes.py). Every action goes
into the stop record with its undo. A row per run goes to <root>/log.jsonl, <root> being $IMPORTANT_INTERRUPT_ROOT
or ~/skills/important-interrupt.
--dry-run prints every action it would take and changes nothing: no record, no log row, no message, no signal.
Exit 0 quiet (or dry run), 4 not quiet within --timeout; done: 0, 1 when no important interrupt is active.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "stop-all-agent-work" / "scripts"))
sys.path.insert(0, str(HERE))
import freeze  # noqa: E402
import messenger  # noqa: E402
import passes  # noqa: E402
import quiet  # noqa: E402
import stopall  # noqa: E402

KIND = "important-interrupt"
STOP_TEXT = (
    "STOP NOW: the user needs a quiet machine (important interrupt{note}). Stop your work right away, mid-step is "
    "fine: run the pause skill (reason: stopped for an important interrupt) so every background shell is frozen, "
    "every subagent, workflow and monitor stopped, every cron job and loop removed, and a pause record written. If "
    "you are in a merge to main (an mtm landing), leave the landing as it is: never abort it, cancel its run or kill "
    "its processes (they are frozen in place with the rest); note in the pause record that a landing was running. "
    "Do not start builds, tests or anything else. Then stay idle until a message from important-interrupt says all "
    "agents may continue; then run the continue skill and, for a landing, run the merge to main again: it adopts "
    "the interrupted landing.")
BUSY = ("working", "starting", "blocked")


class Deps:
    """Everything stop touches, passed in so tests fake the machine, the sessions and the clock."""

    def __init__(self, sys_=None, msg=messenger, qt=quiet, rec=stopall, clock=time.time, sleep=time.sleep,
                 out=print, getpid=os.getpid, idle=None):
        self.sys, self.msg, self.quiet, self.rec = sys_ or freeze.Sys(), msg, qt, rec
        self.clock, self.sleep, self.out, self.getpid = clock, sleep, out, getpid
        self.idle = idle or (lambda: freeze.cpu_idle(self.sys))


def root() -> Path:
    return Path(os.environ.get("IMPORTANT_INTERRUPT_ROOT") or Path.home() / "skills" / "important-interrupt")


def iso(t: float | None) -> str | None:
    return None if t is None else datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")


classify = passes.classify


def last_continue(d: Deps) -> float:
    """When the last system-wide stop was continued (its history file's continued_at), else 0."""
    for f in sorted((d.rec.root() / "history").glob("*.json"), reverse=True):
        try:
            return datetime.fromisoformat(json.loads(f.read_text())["continued_at"]).timestamp()
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return 0.0


def holds(d: Deps, rows: list, t0: float) -> tuple:
    """(to tell, earlier holds as (row, why)), D9: a session in the active stop, or paused on its own before t0
    (a pause record older than t0 but newer than the last system-wide continue, and the session not busy since)."""
    stopped = set()
    if d.rec.record().exists():
        stopped = set(json.loads(d.rec.record().read_text()).get("stopped", []))
    since, tell, held = last_continue(d), [], []
    for r in rows:
        rec = d.msg.pause_record(r)
        mtime = rec.stat().st_mtime if rec.exists() else None
        busy = r.get("status") == "busy" or r.get("state") in BUSY
        if r["name"] in stopped:
            held.append((r, "in an active stop"))
        elif mtime is not None and since < mtime < t0 and not busy:
            held.append((r, "paused earlier"))
        else:
            tell.append(r)
    return tell, held


def update_record(d: Deps, **fields) -> None:
    path = d.rec.record()
    state = json.loads(path.read_text()) if path.exists() else {}
    state.setdefault("kind", KIND)
    state.setdefault("important_interrupt", {}).update(fields)
    path.write_text(json.dumps(state, indent=1) + "\n")


def before(d: Deps, names: list, held: list, note: str) -> dict:
    """Save the stop record; what done needs of the state before it: an earlier stop's record (without its actions,
    which keep their place before first_action) or, on top of an active interrupt, its told and first_action."""
    path = d.rec.record()
    prior = json.loads(path.read_text()) if path.exists() else None
    d.rec.save(names, [], note or KIND)
    prev = (prior or {}).get("important_interrupt")
    if prev:
        told = prev.get("told", []) + [n for n in names if n not in prev.get("told", [])]
        return {"told": told, "first_action": prev.get("first_action", 0), "earlier": prev.get("earlier"),
                "held": [{"name": r["name"], "why": w} for r, w in held if r["name"] not in told]}
    earlier = {k: v for k, v in prior.items() if k != "actions"} if prior else None
    return {"told": names, "first_action": len((prior or {}).get("actions", [])), "earlier": earlier,
            "held": [{"name": r["name"], "why": w} for r, w in held]}


def checkout(d: Deps) -> str:
    code, out, _ = d.sys.run(["git", "rev-parse", "--show-toplevel"])
    return out.strip() if code == 0 and out.strip() else os.getcwd()


def table(d: Deps, rows: list, results: list, paused: dict, held: list, dry: bool) -> None:
    d.out(f"{'session':32} | {'delivered':24} | paused")
    for r, res in zip(rows, results):
        state = "-" if dry else ("yes" if r["name"] in paused else "no answer")
        d.out(f"{str(r['name'])[:32]:32} | {res['status'] + ' ' + str(res['via'] or ''):24} | {state}")
    for r, why in held:
        d.out(f"{str(r['name'])[:32]:32} | {'not told':24} | earlier hold ({why})")


def stop(a, d: Deps) -> int:
    t0, dry = d.clock(), a.dry_run
    me = d.msg.self_pid()
    keep = [checkout(d)]
    rows, held = holds(d, d.msg.sessions(me if me is not None else -1), t0)
    if not dry:
        update_record(d, start=iso(t0), caller=keep[0], **before(d, [r["name"] for r in rows], held, a.note))
    run = passes.Run(d, keep, dry, f"important interrupt{': ' + a.note if a.note else ''}")
    text, mode, results = STOP_TEXT.format(note=f": {a.note}" if a.note else ""), d.msg.caller_mode(me), []

    def tell() -> list:
        results.extend(passes.tell_all(d, rows, text, mode, dry))
        return [r for r in results if r["status"] in ("delivered", "dry-run")]
    run.step("sessions", tell)
    kinds = run.machine()
    if not dry:
        notes = dict(run.notes)
        wq, pq = notes.pop("workqueue quiet", None), notes.pop("pollers quiet", None)
        update_record(d, sources=notes, **({"workqueue_quiet": wq} if wq else {}),
                      **({"pollers_quiet": pq} if pq else {}))
    if dry:
        idle = freeze.cpu_idle(d.sys)
        d.out(f"would re-scan every {passes.RESCAN} s until CPU idle >= {a.idle}% (now {idle}%) and nothing new, "
              f"at most {a.timeout} s; would wait up to {a.reply_wait} s for the sessions to pause")
        run.leftovers()
        table(d, rows, results, {}, held, True)
        return 0
    quiet_at, idle = run.settle(a, t0, kinds)
    run.leftovers()
    paused = passes.replies(d, results, rows, t0, a.reply_wait)
    table(d, rows, results, paused, held, False)
    secs = (quiet_at or d.clock()) - t0
    if quiet_at:
        d.out(f"quiet after {int(secs) // 60}m {int(secs) % 60}s (idle {idle:.0f}%)")
    else:
        d.out(f"not quiet after {a.timeout}s (idle {idle}%): " + "; ".join(freeze.busiest(freeze.proc_table(d.sys))))
    counts = {k: kinds.count(k) for k in sorted(set(kinds))}
    delivered = sum(r["status"] == "delivered" for r in results)
    sessions = [{"name": r["name"], "via": res["via"], "status": res["status"], "paused": r["name"] in paused}
                for r, res in zip(rows, results)]
    update_record(d, quiet_at=iso(quiet_at), seconds=round(secs, 1), idle=idle, sessions=sessions, steps=run.steps,
                  leftovers=run.left)
    log(kind="stop", start=iso(t0), quiet_at=iso(quiet_at), seconds=round(secs, 1), idle=idle, counts=counts,
        told=len(rows), delivered=delivered, paused=len(paused), silent=delivered - len(paused), held=len(held),
        steps=run.steps, dry=False, note=a.note)
    return 0 if quiet_at else 4


def log(**row) -> None:
    path = root() / "log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")


def main(argv=None, deps: Deps | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        argv.insert(0, "stop")
    ap = argparse.ArgumentParser(prog="interrupt.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stop")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--idle", type=float, default=80)
    s.add_argument("--timeout", type=float, default=300)
    s.add_argument("--reply-wait", type=float, default=90)
    s.add_argument("--note", default="")
    for name in ("done", "continue"):
        sub.add_parser(name).add_argument("--dry-run", action="store_true")
    st = sub.add_parser("stats")
    st.add_argument("--json", action="store_true")
    st.add_argument("--last", type=int, default=20)
    a = ap.parse_args(argv)
    import resume  # noqa: E402 (resume imports this module)
    run = {"stop": stop, "done": resume.done, "continue": resume.done, "stats": resume.stats}[a.cmd]
    return run(a, deps or Deps())


if __name__ == "__main__":
    sys.exit(main())
