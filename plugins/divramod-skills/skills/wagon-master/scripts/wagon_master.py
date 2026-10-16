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
      their reasons, who waits, gate train or not (trains.py's steps 1 to 4), and what the yard would give it: the
      files placed and those left with their reasons (yard.py). Nothing is written, merged or sent
  wagon_master.py unhitch <field> --why <text> [--repo <dir>]
      take a field's ready mark; for a car of a red train the duty `trains` goes on in the same call (chain.py):
      the train broken up, its foreman told why, the rest formed again. Refused for a car of a train that lands.
      `unhitch yard`: the yard's car of a red train; its files stay in the yard and out of every train until
      they change, and the farmer is told
  wagon_master.py chain [--in-tick] [--repo <dir>]
      the duty `trains` again, right now, link after link until a wait (chain.py, plan 0333 step 6): what an
      unhitch after red and a round that finds a train landed run, so the next train forms in the same call.
      Only in timer mode, behind the tick lock (`--in-tick`: the round that holds it calls)
  wagon_master.py retry --why <text> [--skip-pretest] [--repo <dir>]
      a red train lands again as it is at the next round (a flaky gate); `--skip-pretest`: without its pretest (a
      red pretest that is the Mac's, not a car's)
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
  wagon_master.py silence | unsilence [--repo <dir>]
      silence the rounds (silence.py, hal2 plan 0349 D6): a real round prints, per train it touched or that stands,
      one table line `| wagon-master | <train> | <state> | joined <fields> |` and nothing else (marker file `silent`
      in the state folder); unsilence ends it. A dry run and --json stay full
  wagon_master.py mode [claude|timer] [--repo <dir>]
      who runs the rounds: the timer (`timer`) or nobody yet (`claude`, the default)
  wagon_master.py checks busy|defer|dispatched|list|cancel|dispatch ... [--repo <dir>] [--json]
      landings first on the runners (hal2 plan 0306, the duty `checks`: checks.py): ci-check asks `busy` and
      defers while a landing runs; checks_cli.py's doc has every command

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
import chain
import checks
import checks_cli
import due
import engine
import learn
import mtm_scan
import role_cli
import roles
import silence
import timer
import train_state
import trains
import wake

HERE = Path(__file__).resolve().parent
WIRING = roles.Wiring(
    role="wagon-master", cli=HERE / "wagon_master.py", skill=HERE.parent,
    act="/wagon-master act", handoff="/wagon-master handoff", duties=("mtm", "trains", "checks", "learn"),
    subskills={"mtm": "merge-to-main-boss", "trains": "merge-train"}, carries=train_state.carries,
    session_effort=True)
# "duty:<name>" → (item, ctx) → actions
HANDLERS: dict = {"duty:mtm": boss.handler, "duty:trains": trains.handler, "duty:checks": checks.handler,
                  "duty:learn": learn.handler}


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
    sub.add_parser("chain").add_argument("--in-tick", action="store_true")
    sub.add_parser("retry").add_argument("--skip-pretest", action="store_true")
    for name in ("unhitch", "retry"):
        sub.choices[name].add_argument("--why", required=True)
    for name in ("silence", "unsilence"):
        sub.add_parser(name)
    sub.add_parser("mode").add_argument("set", nargs="?", choices=role_cli.MODES)
    for x in sub.choices.values():
        x.add_argument("--repo", default=os.getcwd())
    checks_cli.add_parser(sub)  # its commands take their own --repo
    return p


def main(argv: list[str]) -> int:
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    args = parser().parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    if args.cmd == "checks":
        args.argv = rest
        return checks_cli.main(args, status, WIRING)
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
                      else engine.retry(args.repo, args.why, skip_pretest=args.skip_pretest))
        print(text, file=sys.stderr if code else sys.stdout)
        return code or (go_on(args.repo) if args.cmd == "unhitch" else 0)
    if args.cmd == "chain":
        code, text = chain.run(args.repo, WIRING, trains.handler, args.in_tick)
        print(text)
        return code
    if args.cmd in ("silence", "unsilence"):
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
    return tick(args)


STATE = {"formed": "formed", "started": "landing", "red": "red", "retry": "lands again", "landed": "in the barn",
         "cleared": "broken up"}


def silent_lines(main: str, r: dict, since: str, wiring: roles.Wiring = WIRING) -> list[str]:
    """A silenced round (silence.py): one table line per train that changed since `since` (UTC, train_state.utc) or
    stands now, `joined` the fields that rode it (the yard as `yard`); none: a line saying so."""
    if r.get("problem"):
        return silence.round_lines(r, wiring)
    rows = train_state.lines(main)
    names = list(dict.fromkeys(e["train"] for e in rows if e.get("train") and e.get("at", "") >= since))
    stands = train_state.standing(rows)
    if stands and stands["train"] not in names:
        names.append(stands["train"])
    out = []
    for name in names:
        mine = [e for e in rows if e.get("train") == name]
        formed = next((e for e in mine if e["kind"] == "formed"), {})
        state = next((STATE[e["kind"]] for e in reversed(mine) if e["kind"] in STATE), "formed")
        joined = [c["field"] for c in formed.get("cars", [])] + (["yard"] if any(e["kind"] == "yard" for e in mine) else [])
        out.append(silence.line(wiring.role, f"train {name}: {state}", joined))
    return out or [silence.line(wiring.role, "no train")]


def go_on(repo: str) -> int:
    """After an unhitch: a red train split by it is broken up and the rest formed again in this call (cause C)."""
    train = train_state.standing(train_state.lines(mtm_scan.main_checkout(repo)))
    if not train or train["state"] != "split":
        return 0
    code, text = chain.run(repo, WIRING, trains.handler)
    print(text)
    board.safely(mtm_scan.main_checkout(repo), "messages and acks", board.sync)
    return code


def tick(args) -> int:
    """A round, with the message board's messages and acks (the frame's log) posted before and after it (step 7);
    a dry run writes nothing."""
    main_dir = mtm_scan.main_checkout(args.repo)
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
