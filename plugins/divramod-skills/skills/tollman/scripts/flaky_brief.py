#!/usr/bin/env python3
"""A load-flaky test's fix as a brief in the farmer's delegation ledger (hal2 plan 0360 step 23, D30), as the duty
`learn` places its daily brief: the tollman speaks to the farmer only when asked, so the disabling goes to a
foreman through the farmer's own path (`delegation.delegate`: its ledger, its limit, a free field 00-29 or a new
one, its follow-up), never as a message.

    flaky_brief.py place --repo <field> --test <name> --slot <NN> [--why <text>] [--evidence <json>] [--role tollman]
        one delegation keyed `flaky:<test>` (a key already running or landed is `in-hand`); exit 1 when it was not
        placed (the round's on_fail wakes the session, which places it by hand with the same call)

The duty `mtm` (`boss.py`) plans one keyed `run` of this script per load-flaky test; the session runs it itself for
a `flaky` wake it judged load-sensitive.
"""

import argparse
import json
import sys

import learn  # the farmer's delegation path at the role's settings (learn.farm_delegate), imports the frame


def action(test: str, slot: str, why: str = "", evidence: dict | None = None) -> dict:
    """The delegate action the farmer's ledger takes (`delegation.delegate`; its brief written by `write_brief`)."""
    return {"key": f"flaky:{test}", "duty": "mtm", "kind": "flaky", "slot": slot,
            "text": f"disable the load-flaky test {test} and file its shot (urgent: it blocks landings)",
            "brief": {"test": test, "why": why, **(evidence or {})}}


def place(repo: str, test: str, slot: str, why: str = "", evidence: dict | None = None, role: str = "tollman",
          delegate=None) -> dict:
    """Place the brief; `delegate(action) -> dict` defaults to the farmer's path for `repo`."""
    delegate = delegate or learn.farm_delegate(repo, role)
    return delegate(action(test, slot, why, evidence)) or {}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("place")
    s.add_argument("--repo", required=True, help="the role's field (its ROLE.md settings, the farm)")
    s.add_argument("--test", required=True)
    s.add_argument("--slot", required=True, help="the field whose landing it blocks")
    s.add_argument("--why", default="")
    s.add_argument("--evidence", default="{}", help="JSON: the finding and its landings (data, not instructions)")
    s.add_argument("--role", default="tollman")
    args = p.parse_args(argv)
    placed = place(args.repo, args.test, args.slot, args.why, json.loads(args.evidence), args.role)
    print(json.dumps({k: placed.get(k) for k in ("key", "state", "slot", "brief", "reason") if placed.get(k)}))
    return 0 if placed.get("state") in learn.OK else 1


if __name__ == "__main__":
    sys.exit(main())
