#!/usr/bin/env python3
"""A smuggle pauses the train (hal2 plan 0360 step 18, D58, D60): hal2-git pauses the carrier's landing in place
(`paused_by {slot, seq, since}` on its ticket in `queue --json`; ci/pause.rs), cancels its land runs that have not
started merging, and resumes it on the new main by itself. The tollman only reads and reacts:

1. `of`: the carrier's ticket's `paused_by`, or None.
2. `step` (trains.plan, before anything else for a train `landing` or `paused`): a pause not yet recorded is one
   `pause` line of train.jsonl (the run watched then, so triage.paused_by knows the run the pause cancelled), its
   action's text the tick.log line "paused by smuggle <slot> since <t>", once per pause (`seq`); while paused,
   nothing else: no wake, no restart, no car leaves, no hitch joins (D3). Only a landing whose process ended landed
   settles the normal way (a run whose merge succeeded ships as hal2-git lets it, D59).
3. The ticket without `paused_by` while the train is `paused`: a `resumed` line ("resumed after smuggle <slot>(s)"),
   the train `landing` again with its land run forgotten, so watch.py finds the newer run (created after the pause).
   A landing whose process ended `paused` (its slice ended first) is started again by settle (trains.AGAIN).

  pause.py pause --field <slot> --seq <n> --since <t> [--run <url>] [--repo <dir>]   the line of 2
  pause.py resumed [--repo <dir>]                                                    the line of 3
"""

import argparse
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import train_state
from tick import act

HERE = Path(__file__).resolve()
STATES = ("landing", "paused")
LANDED = ("landed", "nothing")  # trains.LANDED
TEXT = {
    "paused": "train {train} is paused by smuggle {slot} since {since}",
    "resumed": "train {train} resumed after smuggle {slots}",
}


def of(ticket: dict | None) -> dict | None:
    """The smuggle that paused the ticket: {slot, seq, since}, or None."""
    by = (ticket or {}).get("paused_by")
    return {"slot": by.get("slot"), "seq": by.get("seq"), "since": by.get("since")} if by else None


def action(top: str, kind: str, key: str, text: str, *args: str) -> dict:
    """A `run` of this script's verb; a failed one wakes the session once."""
    argv = [sys.executable, str(HERE), *args, "--repo", top]
    stuck = act("trains", "train-stuck", "wake", key=f"stuck:{key}",
                text=f"{text}: not noted, run `{' '.join(argv[1:])}` to see why")
    return act("trains", kind, "run", "-", key=key, argv=argv, text=text, on_fail=[stuck])


def landed(result: dict | None) -> bool:
    status = (result or {}).get("status")
    return status in LANDED or (status == "shipping" and bool(result.get("commit")))


def slots(train: dict) -> str:
    """The smuggles of the pauses since the last resume, as the text names them."""
    return ", ".join(dict.fromkeys(p["field"] for p in train.get("pauses", [])[train.get("resumed", 0):]))


def step(top: str, main: str, train: dict | None, mine: dict, alive, result) -> tuple[list[dict], dict | None, bool]:
    """(the actions, the train as the rest of the round sees it, whether the round stops here) (see the doc)."""
    if not train or train["state"] not in STATES:
        return [], train, False
    by, name = of(mine), train["train"]
    if by and not alive(train.get("pid")) and landed(result(main)):
        return [], dict(train, state=train.get("paused_from") or train["state"]), False
    if by:
        if any(p.get("seq") == by["seq"] for p in train.get("pauses", [])):
            return [], train, True
        run = train.get("land_run") or ""
        return [action(top, "train-paused", f"pause:{name}:{by['seq']}", TEXT["paused"].format(train=name, **by),
                       "pause", "--field", by["slot"], "--seq", str(by["seq"]), "--since", by["since"],
                       *(["--run", run] if run else []))], train, True
    if train["state"] != "paused":
        return [], train, False
    seq = train["pauses"][-1].get("seq")
    out = action(top, "train-resumed", f"resumed:{name}:{seq}", TEXT["resumed"].format(train=name, slots=slots(train)),
                 "resumed")
    return [out], train_state.resume(dict(train)), False


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb", required=True)
    paused = sub.add_parser("pause")
    paused.add_argument("--field", required=True)
    paused.add_argument("--seq", type=int, required=True)
    paused.add_argument("--since", required=True)
    paused.add_argument("--run")
    for verb in (paused, sub.add_parser("resumed")):
        verb.add_argument("--repo", default=".")
    a = p.parse_args(argv)
    home = mtm_scan.main_checkout(a.repo)
    train = train_state.standing(train_state.lines(home))
    if not train or train["state"] not in STATES:
        print(f"no landing train stands ({(train or {}).get('state', 'none')}): nothing noted")
        return 0
    if a.verb == "pause":
        train_state.append(home, "pause", train["carrier"], train=train["train"], field=a.field, seq=a.seq,
                           since=a.since, run=a.run)
        print(TEXT["paused"].format(train=train["train"], slot=a.field, since=a.since))
    elif train["state"] == "paused":
        train_state.append(home, "resumed", train["carrier"], train=train["train"], field=slots(train))
        print(TEXT["resumed"].format(train=train["train"], slots=slots(train)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
