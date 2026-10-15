#!/usr/bin/env python3
"""The wagon master's deterministic side (hal2 plan 0294, D7): its rounds on the farmer skill's frame.

  wagon_master.py start-check [--repo <dir>] [--json]
      may the wagon master start here? Its field `wagon-master-<repo>` holding nothing but roles/wagon-master/
      ROLE.md changes, the tools, a valid role file; prints the loop's cron
  wagon_master.py tick [--repo <dir>] [--dry-run [--all-due]] [--json]
      one round as code (the frame's tick.py): stay current, the user's role file edit, the due duties (`mtm`:
      boss.py, `trains`: trains.py plans, engine.py does, `learn`: learn.py once a day), the log, the summary;
      what needs judgment is collected as `wake`. --dry-run plans the round and touches nothing. Outside a dry run
      a tick runs only in timer mode. While a train stands the field holds its cars and the round neither merges
      from main nor commits a role file edit (D22). Outside a dry run the round's messages and acks (the frame's
      log) are posted to the message board before and after it (board.py sync)
  wagon_master.py train --dry-run [--json] [--repo <dir>]
      the train that stands and the next one as the queue allows it now: the cars in order, the unhitched with
      their reasons, who waits, alone or not (trains.py's steps 1 to 4), and what the yard would give it: the
      files placed and those left with their reasons (yard.py). Nothing is written, merged or sent
  wagon_master.py unhitch <field> --why <text> [--repo <dir>]
      take a field's ready mark; for a car of a red train the rest forms again at the next round, and the tick
      tells its foreman why. Refused for a car of a train that lands. `unhitch yard`: the yard's car of a red
      train; its files stay in the yard and out of every train until they change, and the farmer is told
  wagon_master.py retry --why <text> [--repo <dir>]
      a red train lands again as it is at the next round (a flaky gate)
  wagon_master.py timer install|remove|status [--repo <dir>] [--dry-run] [--json]
      the external timer `local.wagon-master.<repo>` that runs `tick` at the loop's cron (the frame's timer.py);
      install switches the mode to `timer`, remove back to `claude`
  wagon_master.py status [--repo <dir>] [--json]
      is there a wagon master here: its field, its timer and mode, its last tick with its age in seconds, the wake
      items not handled yet (what a foreman's /mtm asks before it hitches, D13)
  wagon_master.py act [--done <seq>] [--repo <dir>] [--json]
      what the tick handed to the wagon master's session (wake.json: each item with the file to read for it);
      --done drops the items up to <seq> once handled
  wagon_master.py handoff [--clear] [--repo <dir>]
      the handoff before the session's clear: the path of handoff.md in the state folder; --clear, once it is
      written, starts hal2's clear-and-continue (/clear, then /wagon-master act)
  wagon_master.py mode [claude|timer] [--repo <dir>]
      who runs the rounds: the timer (`timer`) or nobody yet (`claude`, the default)

The message board is board.py (`board.py list`, `post`, `sync`): roles/wagon-master/board.jsonl.

State: roles/wagon-master/ of the field wagon-master-<repo> ($FARMER_DIR/<repo>/wagon-master/ overrides it), never
the farmer's folder; its files are declared in the skill's manifest.toml (the train state: train_state.py). No
delegations of its own and no `task:*` (D22): the duty `learn`'s one daily brief goes into the farmer's delegation
ledger (learn.py, plan 0313 D8). Exit codes as the frame's role_cli.py; `unhitch` and `retry` exit 1 when refused.
"""

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import board
import boss
import due
import engine
import learn
import mtm_scan
import role_cli
import roles
import timer
import train_state
import trains
import wake

HERE = Path(__file__).resolve().parent
WIRING = roles.Wiring(
    role="wagon-master", cli=HERE / "wagon_master.py", skill=HERE.parent,
    act="/wagon-master act", handoff="/wagon-master handoff", duties=("mtm", "trains", "learn"),
    subskills={"mtm": "merge-to-main-boss", "trains": "merge-train"}, carries=train_state.carries)
# "duty:<name>" → (item, ctx) → actions
HANDLERS: dict = {"duty:mtm": boss.handler, "duty:trains": trains.handler, "duty:learn": learn.handler}


def last_tick(state: Path) -> dt.datetime | None:
    """When the last round ran: the newest of the log's entries written by a tick and the run records."""
    at = [e["at"] for e in mtm_scan.entries(state / "log.jsonl") if e.get("by") == "tick"]
    runs = state / "runs.jsonl"
    at += [json.loads(line)["at"] for line in runs.read_text().splitlines()] if runs.exists() else []
    return max(map(dt.datetime.fromisoformat, at), default=None)


def status(repo: str, now: dt.datetime | None = None) -> dict:
    """The wagon master of `repo`'s farm as data, from any checkout of it; a farm without the field has no state
    (nothing is created for it): no timer file, no last tick."""
    field, state = roles.slot_dir(repo, WIRING.role), role_cli.state(repo, WIRING)
    last = last_tick(state)
    age = int(((now or dt.datetime.now()) - last).total_seconds()) if last else None
    return {"role": WIRING.role, "field": str(field), "field_exists": field.is_dir(),
            "timer": timer.status(due.repo_name(repo), state, WIRING), "mode": role_cli.mode(repo, WIRING),
            "last_tick": last.isoformat(timespec="seconds") if last else None, "last_tick_age_s": age,
            "pending": len(wake.read(mtm_scan.main_checkout(repo), WIRING)["items"])}


def print_status(s: dict) -> None:
    t = s["timer"]
    print(f"{s['field']}: {'exists' if s['field_exists'] else 'no field'}")
    print(f"timer {t.get('label', '-')}: {'loaded' if t.get('loaded') else 'not loaded'}, cron {t.get('cron', '-')}, "
          f"mode {s['mode']}")
    print(f"last tick: {s['last_tick'] or 'never'}"
          + (f" ({s['last_tick_age_s']} s ago)" if s["last_tick"] else "") + f"; {s['pending']} wake items")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("start-check", "tick", "status", "act", "timer"):
        sub.add_parser(name).add_argument("--json", action="store_true")
    sub.choices["tick"].add_argument("--dry-run", action="store_true")
    sub.choices["tick"].add_argument("--all-due", action="store_true")
    sub.choices["act"].add_argument("--done", type=int)
    sub.choices["timer"].add_argument("action", choices=("install", "remove", "status"))
    sub.choices["timer"].add_argument("--dry-run", action="store_true")
    sub.add_parser("handoff").add_argument("--clear", action="store_true")
    train = sub.add_parser("train")
    train.add_argument("--dry-run", action="store_true", required=True)
    train.add_argument("--json", action="store_true")
    sub.add_parser("unhitch").add_argument("field")
    sub.add_parser("retry")
    for name in ("unhitch", "retry"):
        sub.choices[name].add_argument("--why", required=True)
    sub.add_parser("mode").add_argument("set", nargs="?", choices=role_cli.MODES)
    for x in sub.choices.values():
        x.add_argument("--repo", default=os.getcwd())
    return p


def main(argv: list[str]) -> int:
    args = parser().parse_args(argv)
    if args.cmd == "start-check":
        return role_cli.print_start_check(*role_cli.start_check(args.repo, WIRING), args.json)
    if args.cmd == "status":
        s = status(args.repo)
        print(json.dumps(s, indent=1)) if args.json else print_status(s)
        return 0
    if args.cmd == "train":
        d = trains.dry_run(args.repo)
        print(json.dumps(d, indent=1)) if args.json else trains.print_dry_run(d)
        return 0
    if args.cmd in ("unhitch", "retry"):
        code, text = (engine.unhitch(args.repo, args.field, args.why) if args.cmd == "unhitch"
                      else engine.retry(args.repo, args.why))
        print(text, file=sys.stderr if code else sys.stdout)
        return code
    if args.cmd == "act":
        return role_cli.run_wake(args, WIRING)
    if args.cmd == "handoff":
        return role_cli.run_handoff(args, WIRING)
    if args.cmd == "timer":
        return role_cli.run_timer(args, WIRING)
    if args.cmd == "mode":
        if args.set:
            role_cli.set_mode(args.repo, WIRING, args.set)
        print(role_cli.mode(args.repo, WIRING))
        return 0
    return tick(args)


def tick(args) -> int:
    """A round, with the message board's messages and acks (the frame's log) posted before and after it (step 7);
    a dry run writes nothing."""
    main_dir = mtm_scan.main_checkout(args.repo)
    if not args.dry_run:
        board.safely(main_dir, "messages and acks", board.sync)
    code = role_cli.run_tick(args.repo, args.dry_run, args.json, HANDLERS, WIRING, args.all_due)
    if not args.dry_run:
        board.safely(main_dir, "messages and acks", board.sync)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
