#!/usr/bin/env python3
"""The farmer's deterministic side: what runs without a model (.adr/deterministic-first.md, plan 0007).

  farmer.py start-check [--repo <dir>] [--json]
      may the farmer start here? The farmer slot, holding nothing but roles/farmer/ROLE.md changes, the
      tools, a valid roles/farmer/ROLE.md; prints the loop's cron
  farmer.py tick [--repo <dir>] [--dry-run [--all-due]] [--json]
      one round as code: stay current (merge-from-main), the user's roles/farmer/ROLE.md edit, what is due,
      each due item's actions, the log, the summary. Items that need judgment are collected as
      `wake`, notices for the user as `notify`. --dry-run plans the round and touches nothing; --all-due (dry runs
      only) counts every opted-in duty and task due, to measure a full round. Ends with a `timing:` line: the
      seconds of the frame, each due item (planning and execution), delegations, wake, summary and the total
  farmer.py delegate --brief <file> --title <title> [--repo <dir>] [--dry-run] [--json]
      hand a brief the woken farmer wrote to a servant (the same limit, slot choice, prompt and ledger as the tick's
      delegations); --dry-run prints the calls it would make
  farmer.py check task <name> | flaky | orphans [--repo <dir>]
      a task's Check (machine form, see tasks.py), or a built-in check for roles/farmer/ROLE.md tasks: flaky ledger
      entries whose servant runs no plan, slots with work and no session; exit 0 fine, 1 with what is wrong
  farmer.py wake [--done <seq>] [--repo <dir>] [--json]
      what the tick handed to the farmer session (wake.json: items that need judgment, relays, notices, failed
      delegations, each with the file to read for it); --done drops the items up to <seq> once handled
  farmer.py handoff [--clear] [--repo <dir>]
      the farmer's handoff before its clear (handoff.py): the path of handoff.md in the state folder (its sections
      when it is missing); --clear, once it is written, starts hal2's clear-and-continue (/clear, then /farmer act)
  farmer.py decision-check (--message <text> | <slot> --have <list>) [--repo <dir>] [--dry-run]
      answer a servant's `decision check <slot>: I have these decisions: ...` (decision_check.py): the log's
      `decision` entries for the slot that neither its list nor its checkout (HANDOFF.md, current plan, INTENT.md)
      holds, with the user's words quoted, or "none missing"; exit 1 for an unknown slot. Logs the check (kind `decision-check`) unless --dry-run; superseded decisions never count
  farmer.py decision list [--slot <slot>] [--all] | supersede <at>... --by <at> [--why <text>] [--dry-run]
      the user's current decisions in the log; mark ones a later decision replaced (decision_log.py)
  farmer.py timer install|remove|status [--repo <dir>] [--dry-run] [--json]
      the external timer that runs `tick` at the loop's cron (launchd on macOS, a systemd user timer on Linux;
      timer.py); install switches the mode to `timer`, remove back to `claude`
  farmer.py migrate [--role <role>] [--repo <dir>] [--dry-run] [--json]
      move a role's slot `<role>` to `<role>-<project>` with its files in roles/<role>/ (migrate.py, hal2 plan 0143):
      refuses while the timer is installed or a session sits in the slot; idempotent
  farmer.py mode [claude|timer] [--repo <dir>]
      who runs the rounds: the farmer's Claude session (`claude`, the default) or the external
      timer (`timer`). A tick without --dry-run runs only in timer mode, so the two never overlap.

State: roles/farmer/ of the farmer slot farmer-<repo> (roles.py; $FARMER_DIR/<repo>/ overrides it): mode, tick.lock, log.jsonl, runs.jsonl, wake.json,
timer.json, tick.log, handoff.md, summaries/; its .gitignore ignores all but ROLE.md and itself.
Exit 0 ok (also: another tick holds the lock, `busy`), 1 roles/farmer/ROLE.md invalid, 2 a tool missing,
3 no roles/farmer/ROLE.md, 4 not the farmer slot (or one still named `farmer`: migrate first), a slot holding other work, or not in timer mode.
"""

import argparse
import datetime
import fcntl
import json
import os
import shutil
import sys
from pathlib import Path

import boss
import decision_check
import decision_log
import delegation
import due
import duties
import role_sync
import roles
import handoff
import migrate
import prune
import tasks
import tick
import timer
import trains
import wake

HERE = Path(__file__).resolve().parent
TOOLS = ("git", "gh", "hal2-cli-git", "hal2-cli-agents")
MODES = ("claude", "timer")
HANDLERS: dict = {  # "duty:<name>" / "task:<name>" → (item, ctx) → planned actions
    "duty:mtm": boss.handler,
    "duty:lead": duties.plan_lead,
    "duty:ci": duties.plan_ci,
    "duty:prs": duties.plan_prs,
    "duty:sync": role_sync.plan_sync,
    "duty:watch": duties.plan_watch,
    "duty:autoclear": duties.plan_autoclear,
    "duty:trains": trains.handler,
    "duty:prune": prune.handler,
    "task:*": tasks.plan_task,
}


def state(repo: str) -> Path:
    return roles.state_dir(repo, due.DATA)


def mode(repo: str) -> str:
    f = state(repo) / "mode"
    text = f.read_text().strip() if f.exists() else ""
    return text if text in MODES else "claude"


def start_check(repo: str) -> tuple[int, dict]:
    missing = [t for t in TOOLS if not shutil.which(t)]
    if missing:
        return 2, {"ok": False, "problems": [f"missing {', '.join(missing)}: run {HERE}/install-prerequisites.sh"]}
    problem = tick.slot_problem(repo)
    if problem:
        return 4, {"ok": False, "problems": [problem]}
    top = tick.git(repo, "rev-parse", "--show-toplevel")
    role = Path(top) / tick.ROLE
    if not role.exists():
        return 3, {"ok": False, "problems": [f"no {role}: nothing is opted in (template: templates/ROLE.md)"]}
    items, settings, problems = due.schedule(role.read_text())
    if problems:
        return 1, {"ok": False, "problems": problems}
    return 0, {"ok": True, "loop_cron": due.loop_cron(items), "settings": settings, "mode": mode(top),
               "items": sorted(items)}


def print_round(r: dict) -> None:
    head = "dry run" if r["dry"] else "round"
    if r.get("problem"):
        print(f"farmer tick ({head}): {r['problem']}")
        return
    print(f"farmer tick ({head}): {len(r.get('due', []))} due"
          + (f": {', '.join(i['name'] for i in r['due'])}" if r.get("due") else ""))
    for a in r["planned"]:
        what = a.get("text") or " ".join(a.get("argv", [])) or a.get("name", "")
        print(f"- {a['do']:6} {a['duty']}/{a['kind']} {a['slot']}: {what}")
    for key in ("relay", "delegate", "wake", "notify"):
        if r.get(key):
            print(f"{key}: " + "; ".join(a.get("text", "") for a in r[key]))
    if r.get("woke"):
        w = r["woke"]
        print(f"wake: {w['pending']} pending" + (", farmer woken" if w["woken"] else f" ({w['why']})" if w.get("why")
                                                 else ""))
    if r.get("summary"):
        print(f"summary: {r['summary']}")
    if r.get("timing"):
        print(tick.timing_line(r["timing"], r.get("gh")))


def run_tick(repo: str, dry: bool, as_json: bool, all_due: bool = False) -> int:
    missing = [t for t in TOOLS if not shutil.which(t)]
    if missing:
        print(f"farmer.py: missing {', '.join(missing)}; run {HERE}/install-prerequisites.sh", file=sys.stderr)
        return 2
    if not dry and mode(repo) != "timer":
        print("farmer.py: mode is `claude` (the farmer's Claude loop runs the rounds); a tick runs only in timer mode "
              "(`farmer.py mode timer`), or use --dry-run", file=sys.stderr)
        return 4
    if all_due and not dry:
        print("farmer.py: --all-due only measures: use it with --dry-run", file=sys.stderr)
        return 4
    with (state(repo) / "tick.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("busy: another tick runs")
            return 0
        timer.rotate(state(repo))
        r = tick.run(repo, dry, HANDLERS, all_due=all_due)
        if not dry and not r.get("problem"):
            follow_cron(repo)
    print(json.dumps(r, indent=1, default=str) if as_json else "", end="")
    if not as_json:
        print_round(r)
    return 4 if r.get("problem") else 0


def follow_cron(repo: str) -> None:
    """Reinstall the timer when roles/farmer/ROLE.md changed the loop's cron."""
    code, check = start_check(repo)
    st = state(repo)
    if code == 0 and timer.installed(st).get("cron") not in (None, check["loop_cron"]):
        timer.install(due.repo_name(repo), tick.git(repo, "rev-parse", "--show-toplevel"), st, check["loop_cron"])
        print(f"timer: loop cron now {check['loop_cron']}")


def run_timer(args) -> int:
    st, name = state(args.repo), due.repo_name(args.repo)
    if args.action == "status":
        r = timer.status(name, st) | {"mode": mode(args.repo)}
        print(json.dumps(r, indent=1) if args.json else
              f"{r['label']}: {'loaded' if r['loaded'] else 'not loaded'}, cron {r.get('cron', '-')}, mode {r['mode']}")
        return 0
    if args.action == "remove":
        cmds = timer.remove(name, st, args.dry_run)
    else:
        code, check = start_check(args.repo)
        if code:
            print("\n".join(f"- {x}" for x in check["problems"]), file=sys.stderr)
            return code
        top = tick.git(args.repo, "rev-parse", "--show-toplevel")
        try:
            cmds = timer.install(name, top, st, check["loop_cron"], args.dry_run)
        except (RuntimeError, ValueError) as e:
            print(f"farmer.py: {e}", file=sys.stderr)
            return 2
    print("\n".join(" ".join(c) for c in cmds) if args.dry_run else f"{args.action}: mode {mode(args.repo)}")
    return 0


def run_wake(args) -> int:
    main = tick.mtm_scan.main_checkout(args.repo)
    if args.done is not None:
        print(f"{wake.done(main, args.done)} items left")
        return 0
    data = wake.read(main)
    if handoff.path(main).exists() and not args.json:
        print(f"read first: {handoff.path(main)}")
    if args.json:
        print(json.dumps(data, indent=1))
        return 0
    for i in data["items"]:
        print(f"{i['seq']:3} {i['do']:6} {i['duty']}/{i['kind']} {i['slot']}: {i.get('text', '')}\n"
              f"    read {i['instructions']}")
    print(f"{len(data['items'])} items" + (f", woken {data['woken_at']}" if data.get("woken_at") else ""))
    return 0


def run_handoff(args) -> int:
    main = tick.mtm_scan.main_checkout(args.repo)
    if not args.clear:
        print(handoff.show(main))
        return 0
    top = tick.git(args.repo, "rev-parse", "--show-toplevel") or args.repo
    code, what = handoff.clear(top, main, datetime.datetime.now())
    print(what)
    return code


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
    return p


def main(argv: list[str]) -> int:
    args = parser().parse_args(argv)

    if args.cmd == "start-check":
        code, result = start_check(args.repo)
        print(json.dumps(result, indent=1) if args.json else
              (f"ok: loop cron `{result['loop_cron']}`, mode {result['mode']}" if result["ok"] else
               "\n".join(f"- {x}" for x in result["problems"])))
        return code
    if args.cmd == "mode":
        if args.set:
            (state(args.repo) / "mode").write_text(args.set + "\n")
        print(mode(args.repo))
        return 0
    if args.cmd == "check":
        what = args.what[1] if args.what[0] == "task" and len(args.what) > 1 else args.what[0]
        code, text = tasks.builtin(" ".join(args.what[1:]) if args.what[0] == "task" else what, args.repo)
        print(text or "ok")
        return code
    if args.cmd == "delegate":
        return run_delegate(args)
    if args.cmd == "wake":
        return run_wake(args)
    if args.cmd == "handoff":
        return run_handoff(args)
    if args.cmd == "timer":
        return run_timer(args)
    if args.cmd == "migrate":
        return migrate.run(args)
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
