#!/usr/bin/env python3
"""The tollman's deterministic side (hal2 plan 0294, D7): its rounds on the farmer skill's frame.

  tollman.py start-check [--repo <dir>] [--json]
      may the tollman start here? Its field `tollman-<repo>` holding nothing but roles/tollman/
      ROLE.md changes, the tools, a valid role file; prints the loop's cron
  tollman.py tick [--repo <dir>] [--dry-run [--all-due]] [--json]
      one round as code (the frame's tick.py): stay current, the user's role file edit, the due duties (`mtm`:
      boss.py, `trains`: trains.py plans, engine.py does, `learn`: learn.py once a day, `prune`: prune.py, the
      landed fields cleaned or removed and after the barn the cars cleared, barn.py, `mainred`: mainred.py, a red
      main rerun when transient, else one wake), the log, the summary;
      what needs judgment is collected as `wake`; the duty `watch` (minute.py, cron `* * * * *`): a tick on which only
      it is due is a minute pass, no round: leavers.check and one line per new event of the live land run, a quiet
      minute prints nothing (plan 0383 step 4); its cost (wall, process starts, gh calls) is one line in
      pass-timing.jsonl of the state folder (pass_timing.py, plan 0480). --dry-run plans the round and touches
      nothing. Outside a dry run a tick runs only in timer mode. While a train stands the field holds its cars and
      the round neither merges from main nor commits a role file edit (D22). Outside a dry run the round's messages
      and acks (the frame's log) are posted to the message board before and after it (board.py sync)
  tollman.py train --dry-run [--json] [--repo <dir>]
      the train that stands and the next one as the queue allows it now: the cars in order, the unhitched with
      their reasons, who waits, alone or not (trains.py's steps 1 to 4), and what the yard would give it: the
      files placed and those left with their reasons (yard.py). Nothing is written, merged or sent
  tollman.py unhitch <field> --why <text> [--by-user] [--repo <dir>]
      take the ready mark of a wagon that rides no train. A car of a formed train is refused: the train is frozen
      (plan 0360 D3, frozen.py), a red one waits for its fix (D7). Only the user's own `--by-user` (never the
      session's) takes a car of a red train out; the duty `trains` then goes on in the same call (chain.py): the
      train broken up, its foreman told why, the rest formed again. `unhitch yard --by-user`: the yard's car of a
      red train; its files stay in the yard and out of every train until they change, and the farmer is told
  tollman.py chain [--in-tick] [--repo <dir>]
      the duty `trains` again, right now, link after link until a wait (chain.py, plan 0333 step 6): what an
      unhitch after red and a round that finds a train landed run, so the next train forms in the same call.
      Only in timer mode, behind the tick lock (`--in-tick`: the round that holds it calls)
  tollman.py retry --why <text> [--skip-pretest] [--repo <dir>]
      a red train lands again as it is at the next round (a flaky gate); `--skip-pretest`: without its pretest (a
      red pretest that is the Mac's, not a car's); a runner fault the round retries by code (triage_cli.py)
  tollman.py triage [<run>] [--json] [--repo <dir>]
      the triage of a land run (the standing train's by default): runner, main (the barn's red) or car, with the
      evidence its wake carries: red jobs, failing tests, each car's files, the log's tail (plan 0360 step 5)
  tollman.py order <field>|main --why <text> [--run <url>] [--post <train>] [--repo <dir>]
      a fix order for the red train's car (or the barn's red, `main`: the tollman's own hand) after the session's
      triage: fix on `<NN>-train-fix` from the carrier's head, push, answer `fixed <sha>` (orders.py, plan 0360 D6);
      `main` with no train standing: the fix is the first car of the next train (own_fix.py, plan 0360 step 8);
      `--post`: a car of that landed train is red after its merge, its fix rides the train that stands (plan 0383 D6)
  tollman.py fixed <field>|main <sha> [--repo <dir>]
      the answer checked and merged into the carrier; the last one: the same cars land again (the round does it by
      code too, from the foreman's ack `done fixed <sha>`); a refused one keeps the order open, the foreman told why
  tollman.py sleep|wake [--by <who>] [--why <text>] [--repo <dir>]
      the tollman's sleep flag (switch.py; plan 0365 D3, 0375): `hal2-cli-roles sleep tollman on|off`, `--by user` by
      default; asleep no train forms, every wagon lands alone in its turn, the hitched told so once
  tollman.py drop --why <text> [--repo <dir>]
      the asleep round's drop of a standing train that is not landing: its mark cleared, its cars keep their places
  tollman.py seen-mode production|smuggle|asleep [--repo <dir>]
  tollman.py barn <field> --head <sha> --how hitch|formed|running [--train <name>] [--repo <dir>]
      the queue's two modes and the flag (modes.py, plan 0360 step 25): what the round saw; a car or hitch already in
      the barn when the tollman wakes from smuggle mode or its flag (a `barn` line; a hitch cleared, a formed train's
      car out)
  tollman.py hold [--why <text>] [--repo <dir>] | unhold [--repo <dir>]
      hold the trains (hold.py, plan 0383 step 7): no train forms, restarts or lands, also not the green merge job's
      next train; the watch, the leavers check, the orders and the board go on and a landing that runs is never cut.
      `status` and each round's `held` line show `held: <why>`; unhold lets the trains form at the next round
  tollman.py timer install|remove|status [--repo <dir>] [--dry-run] [--json]
      the external timer `local.tollman.<repo>` that runs `tick` at the loop's cron (the frame's timer.py);
      install switches the mode to `timer`, remove back to `claude`
  tollman.py status [--repo <dir>] [--json]
      is there a tollman here: its field, its timer and mode, its last tick with its age in seconds, the wake
      items not handled yet (what a foreman's /mtm asks before it hitches, D13)
  tollman.py act [--done <seq>] [--repo <dir>] [--json]
      what the tick handed to the tollman's session (wake.json: each item with the file to read for it); it
      prints handoff.md's `## DO FIRST` first and closes the items older than the handoff's last write (D8);
      --done drops the items up to <seq> once handled
  tollman.py handoff [--rewrite] [--clear] [--repo <dir>]
      the handoff before the session's clear: the path of handoff.md in the state folder; --rewrite first moves
      the old one to handoff-archive/<UTC time>.md (plan 0383 D9); --clear warns above 80 lines and, once it is written, starts hal2's clear-and-continue (/clear, then /tollman act)
  tollman.py silence | unsilence [--repo <dir>]
      silence the rounds (silence.py, hal2 plan 0349 D6): a real round prints, per train it touched or that stands,
      one table line `| tollman | <train> | <state> | joined <fields> |` and nothing else (marker file `silent`
      in the state folder); unsilence ends it. A dry run and --json stay full
  tollman.py mode [claude|timer] [--repo <dir>]
      who runs the rounds: the timer (`timer`) or nobody yet (`claude`, the default)
  tollman.py checks busy|defer|dispatched|list|cancel|dispatch ... [--repo <dir>] [--json]
      landings first on the runners (hal2 plan 0306, the duty `checks`: checks.py): ci-check asks `busy` and
      defers while a landing runs; checks_cli.py's doc has every command

The message board is board.py (`board.py list`, `post`, `sync`): roles/tollman/board.jsonl.

State: roles/tollman/ of the field tollman-<repo> ($FARMER_DIR/<repo>/tollman/ overrides it), never
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
from handlers import HANDLERS  # noqa: F401  (the duties' handlers, imported when asked for)
import minute
import mtm_scan
import pass_timing
import role_cli
import roles

HERE = Path(__file__).resolve().parent


def carries(top: str) -> bool:
    """roles.Wiring.carries: the field holds the trains' cars and the barn's own fix by design (own_fix.py, D22);
    own_fix loads when asked, a minute pass never asks."""
    import own_fix
    return own_fix.carries(top)


WIRING = roles.Wiring(
    role="tollman", cli=HERE / "tollman.py", skill=HERE.parent,
    act="/tollman act", handoff="/tollman handoff", duties=("mtm", "trains", "checks", "learn", "prune", "mainred", "watch"),
    subskills={"mtm": "merge-to-main-boss", "trains": "merge-train"}, carries=carries,
    session_effort=True, min_tick=1)  # min_tick: the duty `watch` ticks every minute (plan 0383 step 4, D4)


def status(repo: str, now: dt.datetime | None = None) -> dict:
    """The tollman of `repo`'s farm as data (status_cmd.py)."""
    import status_cmd
    return status_cmd.status(repo, WIRING, now)


def parser(tick_only: bool = False) -> argparse.ArgumentParser:
    """The commands' parser; `tick_only`: just `tick` (the timer's call), so a pass imports none of the others' modules."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    if tick_only:
        t = sub.add_parser("tick")
        for flag in ("--json", "--dry-run", "--all-due"):
            t.add_argument(flag, action="store_true")
        t.add_argument("--repo", default=os.getcwd())
        return p
    import checks_cli
    import hold
    import modes
    import orders_cli
    import triage_cli
    for name in ("start-check", "tick", "status", "act", "timer"):
        sub.add_parser(name).add_argument("--json", action="store_true")
    sub.choices["tick"].add_argument("--dry-run", action="store_true")
    sub.choices["tick"].add_argument("--all-due", action="store_true")
    sub.choices["act"].add_argument("--done", type=int)
    sub.choices["timer"].add_argument("action", choices=("install", "remove", "status"))
    sub.choices["timer"].add_argument("--dry-run", action="store_true")
    ho = sub.add_parser("handoff")
    ho.add_argument("--clear", action="store_true")
    ho.add_argument("--rewrite", action="store_true")
    train = sub.add_parser("train")
    train.add_argument("--dry-run", action="store_true", required=True)
    train.add_argument("--json", action="store_true")
    sub.add_parser("unhitch").add_argument("field")
    sub.choices["unhitch"].add_argument("--by-user", action="store_true")  # the user's own command (plan 0360 D3)
    sub.add_parser("chain").add_argument("--in-tick", action="store_true")
    sub.add_parser("retry").add_argument("--skip-pretest", action="store_true")
    for name in ("unhitch", "retry"):
        sub.choices[name].add_argument("--why", required=True)
    for name in ("silence", "unsilence"):
        sub.add_parser(name)
    sub.add_parser("mode").add_argument("set", nargs="?", choices=role_cli.MODES)
    triage_cli.add_parser(sub)  # plan 0360 step 5
    orders_cli.add_parser(sub)  # plan 0360 step 6
    modes.add_parser(sub)  # plan 0360 step 25, the switch: plan 0375
    hold.add_parser(sub)  # plan 0383 step 7
    for x in sub.choices.values():
        x.add_argument("--repo", default=os.getcwd())
    checks_cli.add_parser(sub)  # its commands take their own --repo
    return p


def main(argv: list[str]) -> int:
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    args = parser(argv[:1] == ["tick"]).parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    if args.cmd == "tick":
        return tick(args)  # the timer's call: a pass loads no command's module (plan 0480 D3)
    return command(args, rest)


def command(args, rest: list[str]) -> int:
    """Every command but `tick`; each imports what it runs."""
    if args.cmd == "checks":
        import checks_cli
        args.argv = rest
        return checks_cli.main(args, status, WIRING)
    if args.cmd == "start-check":
        return role_cli.print_start_check(*role_cli.start_check(args.repo, WIRING), args.json)
    if args.cmd == "status":
        s = status(args.repo)
        import status_cmd
        print(json.dumps(s, indent=1)) if args.json else status_cmd.show(s)
        return 0
    import hold
    import modes
    if args.cmd == "triage":
        import triage_cli
        return triage_cli.main(args)
    if args.cmd in hold.VERBS:
        return hold.main(args)
    if args.cmd in modes.VERBS:
        return modes.main(args)
    if args.cmd in ("order", "fixed"):
        import orders_cli
        return orders_cli.main(args, WIRING)
    if args.cmd == "train":
        import trains_dry
        d = trains_dry.dry_run(args.repo)
        print(json.dumps(d, indent=1)) if args.json else trains_dry.print_dry_run(d)
        return 0
    if args.cmd in ("unhitch", "retry"):
        import engine_car
        code, text = (engine_car.unhitch(args.repo, args.field, args.why, user=args.by_user) if args.cmd == "unhitch"
                      else engine_car.retry(args.repo, args.why, skip_pretest=args.skip_pretest))
        print(text, file=sys.stderr if code else sys.stdout)
        return code or (go_on(args.repo) if args.cmd == "unhitch" else 0)
    if args.cmd == "chain":
        import chain
        import trains
        code, text = chain.run(args.repo, WIRING, trains.handler, args.in_tick)
        print(text)
        return code
    if args.cmd in ("silence", "unsilence"):
        import silence
        return silence.run(args, WIRING, args.cmd == "silence")
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
    raise SystemExit(f"tollman.py: unknown command {args.cmd}")


def silent_lines(main: str, r: dict, since: str, wiring: roles.Wiring = WIRING) -> list[str]:
    """A silenced round's table lines (silent_lines.py)."""
    import silent_lines as lines
    return lines.of(main, r, since, wiring)


def go_on(repo: str) -> int:
    """After the user's unhitch: a red train split by it is broken up and the rest formed again in this call (cause
    C); the session's unhitch of a car was refused before (plan 0360 D3)."""
    import board
    import chain
    import train_state
    import trains
    train = train_state.standing(train_state.lines(mtm_scan.main_checkout(repo)))
    if not train or train["state"] != "split":
        return 0
    code, text = chain.run(repo, WIRING, trains.handler)
    print(text)
    board.safely(mtm_scan.main_checkout(repo), "messages and acks", board.sync)
    return code


def tick(args) -> int:
    """A round, with the message board's messages and acks (the frame's log) posted before and after it (step 7);
    a dry run writes nothing. None, not even the minute's watch, while the machine is quiet (role_cli.quiet)."""
    if role_cli.quiet(WIRING, args.dry_run):
        return 0
    main_dir = mtm_scan.main_checkout(args.repo)
    if not (args.dry_run or args.json):
        pass_timing.begin()  # a pass is timed from here (light included): wall, processes, gh calls (minute.run)
        if minute.light(args.repo, WIRING):
            return minute.run(args.repo, WIRING)  # only the 1-minute watch is due: no round, a quiet minute prints nothing
        pass_timing.abandon()  # a round has its own timing line
    import board
    import train_state
    if not args.dry_run:
        board.safely(main_dir, "messages and acks", board.sync)
    since = train_state.utc()
    code = role_cli.run_tick(args.repo, args.dry_run, args.json, HANDLERS, WIRING, args.all_due,
                             lambda r, w: silent_lines(main_dir, r, since, w))
    if not args.dry_run:
        board.safely(main_dir, "messages and acks", board.sync)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
