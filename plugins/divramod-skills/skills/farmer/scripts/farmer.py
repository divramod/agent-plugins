#!/usr/bin/env python3
"""The farmer's deterministic side: what runs without a model (.adr/deterministic-first.md, plan 0007).

  farmer.py start-check [--repo <dir>] [--json]
      may the farmer start here? The farmer's worktree, holding nothing but roles/farmer/ROLE.md changes, the
      tools, a valid roles/farmer/ROLE.md; prints the loop's cron
  farmer.py tick [--repo <dir>] [--dry-run [--all-due]] [--json]
      one round as code: stay current (merge-from-main), the user's roles/farmer/ROLE.md edit, what is due,
      each due item's actions, the log, the summary. Items that need judgment are collected as
      `wake`, notices for the user as `notify`. --dry-run plans the round and touches nothing; --all-due (dry runs
      only) counts every opted-in duty and task due, to measure a full round. Ends with a `timing:` line: the
      seconds of the frame, each due item (planning and execution), delegations, wake, summary and the total
  farmer.py delegate --brief <file> --title <title> [--repo <dir>] [--dry-run] [--json]
      hand a brief the woken farmer wrote to a foreman (the same limit, worktree choice, prompt and ledger as the tick's
      delegations); --dry-run prints the calls it would make
  farmer.py check task <name> | flaky | orphans [--repo <dir>]
      a task's Check (machine form, see tasks.py), or a built-in check for roles/farmer/ROLE.md tasks: flaky ledger
      entries whose foreman runs no plan, worktrees with work and no session; exit 0 fine, 1 with what is wrong
  farmer.py wake [--done <seq>] [--repo <dir>] [--json]
      what the tick handed to the farmer session (wake.json: items that need judgment, relays, notices, failed
      delegations, each with the file to read for it); --done drops the items up to <seq> once handled
  farmer.py handoff [--clear] [--repo <dir>]
      the farmer's handoff before its clear (handoff.py): the path of handoff.md in the state folder (its sections
      when it is missing); --clear, once it is written, starts hal2's clear-and-continue (/clear, then /farmer act)
  farmer.py decision-check (--message <text> | <slot> --have <list>) [--repo <dir>] [--dry-run]
      answer a foreman's `decision check <slot>: I have these decisions: ...` (decision_check.py): the log's
      `decision` entries for the worktree that neither its list nor its checkout (HANDOFF.md, current plan, INTENT.md)
      holds, with the user's words quoted, or "none missing"; exit 1 for an unknown worktree. Logs the check (kind `decision-check`) unless --dry-run; superseded decisions never count
  farmer.py decision list [--slot <slot>] [--all] | supersede <at>... --by <at> [--why <text>] [--dry-run]
      the user's current decisions in the log; mark ones a later decision replaced (decision_log.py)
  farmer.py timer install|remove|status [--repo <dir>] [--dry-run] [--json]
      the external timer that runs `tick` at the loop's cron (launchd on macOS, a systemd user timer on Linux;
      timer.py); install switches the mode to `timer`, remove back to `claude`
  farmer.py migrate [--role <role>] [--repo <dir>] [--dry-run] [--json]
      move a role's worktree `<role>` to `<role>-<project>` with its files in roles/<role>/ (migrate.py, hal2 plan 0143):
      refuses while the timer is installed or a session sits in the worktree; idempotent
  farmer.py question add --slot <slot|farmer> --text <Q form> [--waits <what>] | answer <n> --text <a> | drop <n> | list
      the farmer's own question store (questions.jsonl, questions.py); never from prose by hand
  farmer.py questions [a|answered|l|list] [--json] [--repo <dir>]
      the one list of everyone's questions: the farmer's own, the log's open asks, each worktree's store; no model call
  farmer.py silence | unsilence [--repo <dir>]
      silence the farmer's rounds (silence.py, hal2 plan 0349 D6): a real round prints one table line
      `| farmer | <what> | joined <fields> |` and nothing else (marker file `silent` in the state folder); unsilence ends it
  farmer.py mode [claude|timer] [--repo <dir>]
      who runs the rounds: the farmer's Claude session (`claude`, the default) or the external
      timer (`timer`). A tick without --dry-run runs only in timer mode, so the two never overlap.

State: roles/farmer/ of the farmer's worktree farmer-<repo> (roles.py; $FARMER_DIR/<repo>/ overrides it): mode, tick.lock, log.jsonl, runs.jsonl, questions.jsonl, wake.json,
timer.json, tick.log, handoff.md, summaries/; its .gitignore ignores all but ROLE.md and itself.
Exit 0 ok (also: another tick holds the lock, `busy`), 1 roles/farmer/ROLE.md invalid, 2 a tool missing,
3 no roles/farmer/ROLE.md, 4 not the farmer's worktree (or one still named `farmer`: migrate first), a worktree holding other work, or not in timer mode.
"""

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import decision_check
import decision_log
import delegation
import due
import duties
import role_cli
import role_sync
import roles
import silence
import migrate
import questions
import queue_mode
import tasks
import tick

WIRING = roles.FARMER  # the role these rounds run for, passed to every call of the frame (hal2 plan 0294)
MODES = role_cli.MODES
HANDLERS: dict = {  # "duty:<name>" / "task:<name>" → (item, ctx) → planned actions
    "duty:lead": queue_mode.plan_lead,  # plan 0360 step 25: + the smuggle mode's "run /mtm now"
    "duty:ci": duties.plan_ci,
    "duty:prs": duties.plan_prs,
    "duty:sync": role_sync.plan_sync,
    "duty:watch": duties.plan_watch,
    "duty:autoclear": duties.plan_autoclear,
    "task:*": tasks.plan_task,
}


# The commands every role's CLI has live in role_cli.py (the tollman's tollman.py calls the same ones):
# these are the farmer's, under their old names.
def state(repo: str) -> Path:
    return role_cli.state(repo, WIRING)


def mode(repo: str) -> str:
    return role_cli.mode(repo, WIRING)


def start_check(repo: str) -> tuple[int, dict]:
    return role_cli.start_check(repo, WIRING)


def run_tick(repo: str, dry: bool, as_json: bool, all_due: bool = False) -> int:
    return role_cli.run_tick(repo, dry, as_json, HANDLERS, WIRING, all_due)


def follow_cron(repo: str) -> None:
    role_cli.follow_cron(repo, WIRING)


def run_delegate(args) -> int:
    main_dir = tick.mtm_scan.main_checkout(args.repo)
    settings = due.schedule((Path(tick.git(args.repo, "rev-parse", "--show-toplevel") or args.repo)
                             / tick.ROLE).read_text())[1] if (Path(args.repo) / tick.ROLE).exists() else {}
    a = tick.act("farmer", "brief", "delegate", key=f"brief:{delegation.slug(args.title)}", text=args.title,
                 brief={"brief_file": str(Path(args.brief).resolve())})
    result = delegation.delegate(a, main_dir, delegation.parse_limit(settings.get("servant_limit")), args.dry_run,
                                 datetime.datetime.now(), delegation.servant_values(settings))
    print(json.dumps(result, indent=1) if args.json else
          f"{result['state']}: {result.get('slot') or '-'}" + "".join(f"\n  {' '.join(map(str, c))}"
                                                                     for c in result.get("calls", [])))
    return 1 if result["state"] == "error" else 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("start-check")
    t = sub.add_parser("tick")
    t.add_argument("--dry-run", action="store_true")
    t.add_argument("--all-due", action="store_true")
    for x in (sc, t):
        x.add_argument("--repo", default=os.getcwd())
        x.add_argument("--json", action="store_true")
    dg = sub.add_parser("delegate")
    dg.add_argument("--brief", required=True)
    dg.add_argument("--title", required=True)
    dg.add_argument("--repo", default=os.getcwd())
    dg.add_argument("--dry-run", action="store_true")
    dg.add_argument("--json", action="store_true")
    ck = sub.add_parser("check")
    ck.add_argument("what", nargs="+")
    ck.add_argument("--repo", default=os.getcwd())
    w = sub.add_parser("wake")
    w.add_argument("--done", type=int)
    w.add_argument("--repo", default=os.getcwd())
    w.add_argument("--json", action="store_true")
    ho = sub.add_parser("handoff")
    ho.add_argument("--clear", action="store_true")
    ho.add_argument("--repo", default=os.getcwd())
    dc = sub.add_parser("decision-check")
    dc.add_argument("slot", nargs="?")
    dc.add_argument("--have", default="")
    dc.add_argument("--message")
    dc.add_argument("--repo", default=os.getcwd())
    dc.add_argument("--dry-run", action="store_true")
    dl = sub.add_parser("decision")
    dl.add_argument("action", choices=("list", "supersede"))
    dl.add_argument("at", nargs="*")
    dl.add_argument("--by")
    dl.add_argument("--why", default="")
    dl.add_argument("--slot")
    dl.add_argument("--all", action="store_true")
    dl.add_argument("--repo", default=os.getcwd())
    dl.add_argument("--dry-run", action="store_true")
    tm = sub.add_parser("timer")
    tm.add_argument("action", choices=("install", "remove", "status"))
    tm.add_argument("--repo", default=os.getcwd())
    tm.add_argument("--dry-run", action="store_true")
    tm.add_argument("--json", action="store_true")
    mg = sub.add_parser("migrate")
    mg.add_argument("--role", default="farmer", choices=roles.ROLES)
    mg.add_argument("--repo", default=os.getcwd())
    mg.add_argument("--dry-run", action="store_true")
    mg.add_argument("--json", action="store_true")
    m = sub.add_parser("mode")
    m.add_argument("set", nargs="?", choices=MODES)
    m.add_argument("--repo", default=os.getcwd())
    for name in ("silence", "unsilence"):
        sub.add_parser(name).add_argument("--repo", default=os.getcwd())
    questions.add_parsers(sub)
    return p


def main(argv: list[str]) -> int:
    args = parser().parse_args(argv)

    if args.cmd == "start-check":
        return role_cli.print_start_check(*start_check(args.repo), args.json)
    if args.cmd == "mode":
        if args.set:
            role_cli.set_mode(args.repo, WIRING, args.set)
        print(mode(args.repo))
        return 0
    if args.cmd in ("silence", "unsilence"):
        return silence.run(args, WIRING, args.cmd == "silence")
    if args.cmd == "check":
        what = args.what[1] if args.what[0] == "task" and len(args.what) > 1 else args.what[0]
        code, text = tasks.builtin(" ".join(args.what[1:]) if args.what[0] == "task" else what, args.repo)
        print(text or "ok")
        return code
    if args.cmd == "delegate":
        return run_delegate(args)
    if args.cmd == "wake":
        return role_cli.run_wake(args, WIRING)
    if args.cmd == "handoff":
        return role_cli.run_handoff(args, WIRING)
    if args.cmd == "timer":
        return role_cli.run_timer(args, WIRING)
    if args.cmd == "migrate":
        return migrate.run(args)
    if args.cmd in ("question", "questions"):
        return questions.run(args)
    if args.cmd == "decision":
        if args.action == "supersede" and not (args.at and args.by):
            print("farmer.py decision supersede: give the replaced decisions' <at> and --by <at>", file=sys.stderr)
            return 1
        return decision_log.run(args)
    if args.cmd == "decision-check":
        code, text = decision_check.run(args.message or f"decision check {args.slot}: {args.have}", args.repo,
                                        args.dry_run)
        print(text)
        return code
    return run_tick(args.repo, args.dry_run, args.json, args.all_due)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
