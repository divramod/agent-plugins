#!/usr/bin/env python3
"""The start guard of the orphan rule (hal2 plan 0412 step 2, D2, D3): ask the agents list again right before a start
and start only into a field that holds no live session.

    orphan_start.py --path <field folder> --slot <NN> --main <yard> [--role tollman] -- <the start's argv...>

`boss.orphan` plans its `hal2-cli-git worktree run <NN> ... --prompt "/handoff c"` as a run of this script, so the
check happens when the round carries the action out, not when the scan was taken (a scan can be minutes old, a loaded
Mac needed 548 s for it on 2026-10-20). The list is read fresh (`live_sessions.read`, own call) and asked with the
farmer's one lookup (`live_sessions.live_session`): any live session of the field, a terminal host's included, or a
list that cannot be read (fail closed) skips the start: exit 75 (EX_TEMPFAIL, the frame's "did not run, no failure"),
one line saying why on stdout and in the role's log (`orphan-skipped`), no wake. Otherwise the start runs and its
output and exit code are this script's.
"""

import argparse
import subprocess
import sys

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import live_sessions
import mtm_scan

SKIPPED = 75  # EX_TEMPFAIL: tick.OFFLINE, a check that could not start the action is no failure (no on_fail)


def why_skipped(session: dict, slot: str) -> str:
    """The one line: which session holds the field, or that the list could not be read."""
    if session.get("state") == live_sessions.UNKNOWN:
        return f"not started in {slot}: the agents list could not be read, so a session may be there"
    where = session.get("pane_id") or session.get("session") or "a session"
    return f"not started in {slot}: it holds a live session ({session.get('state') or 'no state'}, {where})"


def main(argv: list[str] | None = None, read=live_sessions.read, run=subprocess.run) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--path", required=True, help="the field's folder (the agents list names sessions by it)")
    p.add_argument("--slot", required=True)
    p.add_argument("--main", required=True, help="the main checkout (the role's log)")
    p.add_argument("--role", default="tollman")
    p.add_argument("start", nargs=argparse.REMAINDER, help="-- and the start's argv")
    args = p.parse_args(argv)
    start = args.start[1:] if args.start[:1] == ["--"] else args.start
    if not start:
        p.error("no start argv after --")
    session = live_sessions.live_session(read(), args.path)
    if session:
        line = why_skipped(session, args.slot)
        print(line)
        try:
            mtm_scan.log(args.main, {"kind": "orphan-skipped", "slot": args.slot, "what": line, "note": "start guard"},
                         args.role)
        except OSError:  # no log to write to never makes the start go on
            pass
        return SKIPPED
    done = run(start, capture_output=True, text=True)
    sys.stdout.write(done.stdout or "")
    sys.stderr.write(done.stderr or "")
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
