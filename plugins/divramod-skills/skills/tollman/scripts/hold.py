#!/usr/bin/env python3
"""The hold (hal2 plan 0383 step 7, rule 6, D7): `tollman.py hold [--why <text>]` and `tollman.py unhold`. While the
hold stands, no wagon train forms, restarts or lands: `trains.plan` (the round and the chain: `chain.py`, the green
merge job's next train in `minute.py`, the user's unhitch) returns one `held` line instead of forming. What goes on:
the watch (the minute pass, the live land run's events, leavers.check), fix orders and their answers, the
settling of a landing that landed or ended (never its restart, L107), and a landing that runs: it is never cut
(merge-queue-policy); engine.py reads the hold again right before a start and before the push (L88). It
replaces unloading the timer. The hold is `hold.json` (`why`, `at`, `by`, `words`) in the tollman's state folder;
`status` shows `held: <why>`.

A hold keeps every hitched wagon out of a train, so it is the user's alone (plan 0610 E21; the record
hitch-is-forever): `--by user --words "<the user's words>"`, typed by the user or relayed by the farmer as "the user
decided" (~/.adr/tollman-follows-the-farmer.md). A session's or farmer's own hold, without them, is refused.

  tollman.py hold --by user --words <the user's words> [--why <text>] [--repo <dir>]     hold the trains
  tollman.py unhold [--repo <dir>]                  let them form again (the next round, or `tollman.py chain`)
"""

import json
import sys

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import train_state
from tick import act

FILE = "hold.json"
VERBS = ("hold", "unhold")


def path(main: str):
    return mtm_scan.state_dir(main, train_state.ROLE) / FILE


def of(main: str) -> dict | None:
    """The hold ({why, at}) or None: nothing held (also when the state folder is not there)."""
    try:
        doc = json.loads(path(main).read_text())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


USER = "user"  # the only `--by` a hold takes (E21)
REFUSED = ("no hold: a hold keeps every hitched wagon out of a train, so only the user's own words set one "
           "(`tollman.py hold --by user --words \"<the user's words>\"`, plan 0610 E21); a session's or farmer's own "
           "hold is refused")


def text(held: dict) -> str:
    words = f"; the user's words: \"{held['words']}\"" if held.get("words") else ""
    return f"held: {held.get('why') or held.get('words') or 'no reason given'} (since {held.get('at')}{words})"


def refusal(by: str, words: str) -> str:
    """Why a hold by `by` with `words` is refused, or "" (the user's own words)."""
    return "" if by == USER and words.strip() else REFUSED


def line(held: dict) -> dict:
    """The round's one record of a hold (no key: one tick.log line each round, as `asleep`'s)."""
    return act("trains", "held", "record", text=f"{text(held)}: no train forms or lands; a landing that runs goes on")


def keep(actions: list[dict], held: dict | None) -> list[dict]:
    """A settling landing's actions under the hold `held` (L107): its restart, and the red of a landing that died
    with a fix order open (`died`, plan 0560: that red takes the restart's place, so `fixed` still writes it, L108),
    dropped for the hold's line (an interrupted landing starts again only after `unhold`); landed, red and their
    messages go on."""
    again = [a for a in actions if a.get("kind") == "restart" or a.get("died")]
    if not held or not again:
        return actions
    return [a for a in actions if a not in again] + [line(held)]


def stops(top: str) -> int:
    """The detached landing's last look before merge-to-main pushes (L88: a train formed a minute after the hold
    started its landing): held, it prints the result `held` (trains.AGAIN: started again after `unhold`) and
    returns 1; else 0. Read from the file, never the round's earlier reading."""
    held = of(mtm_scan.main_checkout(top))
    if held:
        print(json.dumps({"status": "held", "message": text(held)}), flush=True)
    return int(bool(held))


def add_parser(sub) -> None:
    h = sub.add_parser("hold")
    h.add_argument("--why", default="")
    h.add_argument("--by", default="", help="who holds: only `user` (plan 0610 E21)")
    h.add_argument("--words", default="", help="the user's own words for the hold")
    sub.add_parser("unhold")


def main(args) -> int:
    main_dir = mtm_scan.main_checkout(args.repo)
    f = path(main_dir)
    if args.cmd == "hold":
        if why := refusal(args.by, args.words):
            print(why)
            return 1
        doc = {"why": args.why, "at": train_state.utc(), "by": USER, "words": args.words.strip()}
        f.write_text(json.dumps(doc) + "\n")
        print(text(of(main_dir)))
        return 0
    held = of(main_dir)
    f.unlink(missing_ok=True)
    print("the trains are held no more: they form at the next round" if held else "no hold was set", file=sys.stdout)
    return 0
