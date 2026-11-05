"""`delegation.py reconcile [--dry-run] [--json] [--repo <repo>] [--limit <n>]` (hal2 plan 0618, D5): the tick's
reconcile of the running delegations run once by hand, the one-off migration of a stale ledger by the same code, never a
hand edit. It gathers the facts once and judges every running entry (delegation_round.judge), then applies the verdicts
(delegation_round.settle: a terminal state written once, a landed foreman's idle session stopped) unless `--dry-run`,
which writes and stops nothing. It prints each entry's verdict with its reason, and the running and working counts (D6)
before and after; waiting briefs are not started here, the tick does that.

`FARMER_DIR` points the state folder at a copy (`$FARMER_DIR/<repo name>/delegations.jsonl`): how it is proven on a copy.
"""

import argparse
import json
import os
import sys

import delegation_round as rnd
import delegation_sync as sync


def reconcile(main: str, slots: dict[str, dict], dry: bool, now, limit: int | str | None = None) -> dict:
    """The report: {dry_run, before, after: {running, working}, waiting, room, entries: [{key, slot, state, to, reason,
    working}]}; applied unless `dry`. `working` is None for the entries judged by no verdict (an unreadable start)."""
    import delegation
    running = rnd.running_entries(main)
    judged, facts = rnd.judge(main, slots, now, running), rnd.working_facts(main, slots)
    works = {e["key"] for e in sync.working([{**e, "key": k} for k, e in running.items()], facts)}
    rows, left = [], []
    for key, entry, v in judged:
        state = v["state"] if v else "running"
        to = v["slot"] if v and v["state"] == "running" else None
        rows.append({"key": key, "slot": entry["slot"], "state": state, "to": to if to != entry["slot"] else None,
                     "reason": v["reason"] if v else "no readable start, left as it is", "working": key in works})
        if state == "running":
            left.append({**entry, "key": key, "slot": to or entry["slot"]})
    if not dry:
        for key, _, v in judged:
            if v is not None:
                rnd.settle(main, key, v, dry, now)
    waiting = sum(e.get("state") == "waiting" for e in delegation.ledger(main).values())
    after = len(sync.working(left, facts))
    return {"dry_run": dry, "before": {"running": len(running), "working": len(works)},
            "after": {"running": len(left), "working": after}, "waiting": waiting,
            "room": max(limit - after, 0) if isinstance(limit, int) else None, "entries": rows}


def text(report: dict) -> str:
    rows = [f"{r['key']}  field {r['slot']}  running -> {r['state']}"
            + (f" in {r['to']}" if r["to"] else "") + ("" if r["working"] else "  [not working]") + f"  ({r['reason']})"
            for r in report["entries"]]
    b, a = report["before"], report["after"]
    head = "reconcile" + (" (dry run, nothing written)" if report["dry_run"] else "")
    room = f", room for {report['room']} more" if report["room"] is not None else ""
    return "\n".join([head, *rows, f"running {b['running']} -> {a['running']}; working {b['working']} -> {a['working']}; "
                      f"waiting {report['waiting']}{room}"])


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="delegation.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reconcile", help="judge every running delegation: landed, gone, moved, still running")
    r.add_argument("--repo", default=os.getcwd())
    r.add_argument("--dry-run", action="store_true", help="write nothing, stop nothing")
    r.add_argument("--json", action="store_true")
    r.add_argument("--limit", type=int, help="the foreman limit, to print the room left")
    return p


def main(argv: list[str] | None = None) -> int:
    import delegation
    import mtm_scan
    import roletime
    import tick
    args = parser().parse_args(argv)
    top = mtm_scan.main_checkout(args.repo)
    report = reconcile(top, tick.slot_state(top), args.dry_run, roletime.utcnow(), args.limit)
    print(json.dumps(report, indent=1) if args.json else text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
