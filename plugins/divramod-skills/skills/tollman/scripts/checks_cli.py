"""`tollman.py checks ...` (hal2 plan 0306, D4, D5): the duty `checks`' commands (checks.py has the rules).

  checks busy [--json]          do the landings have the runners now: {busy, reason, worktree, live, live_why}; `live`:
                                a tollman runs here (its field, its timer loaded in mode `timer`, a round at
                                most 30 minutes old, as mtm's tollman.sh says) and has the duty `checks` opted
                                in, so a deferral is dispatched again. Always exit 0
  checks defer --slot <s> --pane <p> --title <t> [--cwd <dir>] -- <argv...>
                                hold a dispatch back (ci-check, while busy and live); prints the deferral's id
  checks dispatched --slot <s> --pane <p> --title <t> [--run <id>] [--url <u>] [--cwd <dir>] -- <argv...>
                                record a dispatch ci-check made itself, so the duty may cancel and send it again
  checks list [--json]          the deferrals waiting and the checks dispatched today
  checks cancel --run <id>      (the duty's action) cancel a check run that ran nothing but route and changes, and
                                defer it again; exit 1 when refused (a lane job started, not recorded)
  checks dispatch --id <id>     (the duty's action) dispatch a deferral, record its run, supersede the worktree's older
                                deferrals; exit 1 when it is not pending, older than checks.STALE (superseded) or
                                the dispatch failed (recorded `failed`, given up at checks.TRIES)

`<argv>` is the whole command; a command that starts with `workflow` is a gh one (`gh` is put first).
Every command takes `--repo <dir>` (default: the current folder): any checkout of the farm.
"""

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import checks
import due
import mtm_scan
import roles
from tick import sh

MAX_AGE = 1800  # the age of the tollman's last round that still counts as live (mtm's tollman.sh)
COMMANDS = ("busy", "defer", "dispatched", "list", "cancel", "dispatch")


def add_parser(sub) -> None:
    p = sub.add_parser("checks", help="landings first: hold check runs back while a landing runs (plan 0306)")
    cmds = p.add_subparsers(dest="checks", required=True)
    for name in COMMANDS:
        c = cmds.add_parser(name)
        c.add_argument("--repo", default=".")
        c.add_argument("--json", action="store_true")
    for name in ("defer", "dispatched"):
        for flag in ("--slot", "--pane", "--title"):
            cmds.choices[name].add_argument(flag, required=flag != "--pane", default="")
        cmds.choices[name].add_argument("--cwd")
    cmds.choices["dispatched"].add_argument("--run", type=int)
    cmds.choices["dispatched"].add_argument("--url")
    cmds.choices["cancel"].add_argument("--run", type=int, required=True)
    cmds.choices["dispatch"].add_argument("--id", required=True)


def live(repo: str, s: dict, wiring: roles.Wiring) -> tuple[bool, str]:
    """(live, why not) from `tollman.status`'s data and the field's role file."""
    field, timer = Path(s["field"]), s["timer"]
    if not s["field_exists"]:
        return False, f"no tollman here: no worktree {field.name}"
    if Path(mtm_scan.run(["git", "-C", repo, "rev-parse", "--show-toplevel"]).strip() or repo).resolve() \
            == field.resolve():
        return False, "this is the tollman's own worktree"
    if timer.get("loaded") is not True or s["mode"] != "timer":
        return False, f"the tollman's timer is not running (mode {s['mode']})"
    if s["last_tick_age_s"] is None or not 0 <= s["last_tick_age_s"] <= MAX_AGE:
        return False, f"the tollman's last round is {s['last_tick_age_s']} s old (limit {MAX_AGE} s)"
    role = field / wiring.role_file
    if "duty:checks" not in due.schedule(role.read_text() if role.exists() else "", wiring.duties)[0]:
        return False, "the tollman has not opted in to the duty `checks`"
    return True, ""


def busy_report(repo: str, status, wiring: roles.Wiring, run_json=None) -> dict:
    main = mtm_scan.main_checkout(repo)
    s = checks.state(main, run_json or mtm_scan.run_json)
    ok, why = live(repo, status(repo), wiring)
    held = s["busy"] or {}
    return {"busy": bool(held), "reason": held.get("reason", ""), "slot": held.get("slot", ""), "live": ok,
            "live_why": why}


def command(argv: list[str]) -> list[str]:
    return ["gh", *argv] if argv[:1] == ["workflow"] else list(argv)


def flag_of(argv: list[str], flag: str) -> str:
    return next((argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag), "")


def find_run(main: str, entry: dict, since: float, run_json, sleep, tries: int = 6) -> dict | None:
    """The run a dispatch made: the newest dispatch of its branch with its title, created after `since`."""
    branch = flag_of(command(entry["argv"]), "--ref")
    args = ["gh", "run", "list", "--workflow", checks.WORKFLOW, "--event", "workflow_dispatch", "--limit", "10",
            "--json", checks.FIELDS] + (["--branch", branch] if branch else [])
    for n in range(tries):
        for r in run_json(args, main) or []:
            if r.get("displayTitle") == entry.get("title") and checks.mtm_ci.started(r) >= since - 60:
                return r
        if n + 1 < tries:
            sleep(3)
    return None


def dispatch(main: str, entry_id: str, run=sh, run_json=None, sleep=time.sleep, now=None) -> tuple[int, str]:
    rows, now = checks.lines(main), now or dt.datetime.now(dt.timezone.utc)
    entry = next((r for r in checks.pending(rows) if r["id"] == entry_id), None)
    if entry is None:
        return 1, f"no pending deferral {entry_id}"
    if checks.stale(entry, now):  # the worktree's newest is stale, so all of the worktree's are
        gone = checks.supersede_older(main, rows, entry["slot"], "stale", now)
        return 1, f"{entry.get('title')} waited longer than {checks.STALE}: superseded {', '.join(gone)}"
    since = time.time()
    code, out = run(command(entry["argv"]), entry.get("cwd") or main)
    if code:
        n = len(checks.attempts(rows, entry_id)) + 1
        why = f"exit {code}: {out.strip()[-300:]}"
        checks.append(main, "failed", entry["slot"], now, id=entry_id, attempt=n, why=why, pane=entry.get("pane"))
        given = f"; given up after {n} tries" if n >= checks.TRIES else f"; try {n} of {checks.TRIES}"
        return code, f"the dispatch of {entry.get('title')} failed ({why}){given}"
    found = find_run(main, entry, since, run_json or mtm_scan.run_json, sleep) or {}
    keep = {k: entry.get(k) for k in ("id", "pane", "title", "argv", "cwd")}
    checks.append(main, "dispatched", entry["slot"], now, by="checks", run=found.get("databaseId"),
                  url=found.get("url"), **keep)
    checks.supersede_older(main, rows, entry["slot"], entry_id, now)
    return 0, f"dispatched {entry.get('title')}: {found.get('url') or 'run not seen yet'}"


def cancel(main: str, rid: int, run=sh, run_json=None, now=None) -> tuple[int, str]:
    run_json = run_json or mtm_scan.run_json
    view = run_json(["gh", "run", "view", str(rid), "--json", "databaseId,status,displayTitle,url,jobs"], main) or {}
    if view.get("status") == "completed":
        return 0, f"check run {rid} is done already"
    if not view or checks.lane_started(view.get("jobs") or []):
        return 1, f"check run {rid} left alone: " + ("a lane job started" if view else "gh cannot see it")
    entry = checks.recorded(checks.lines(main), view, (now or dt.datetime.now(dt.timezone.utc)))
    if entry is None:
        return 1, f"check run {rid} left alone: not in {checks.FILE}"
    code, out = run(["gh", "run", "cancel", str(rid)], main)
    if code:
        return code, f"gh run cancel {rid} failed (exit {code}): {out[-500:]}"
    checks.append(main, "cancelled", entry["slot"], now, id=entry["id"], run=rid)
    again = checks.append(main, "deferred", entry["slot"], now, id=checks.new_id(entry["slot"], now), again=rid,
                          **{k: entry.get(k) for k in ("pane", "title", "argv", "cwd")})
    return 0, f"cancelled check run {rid}, deferred again as {again['id']}"


def listing(main: str) -> dict:
    rows, cutoff = checks.lines(main), checks.utc(dt.datetime.now(dt.timezone.utc) - checks.TELL)
    return {"pending": checks.pending(rows), "dispatched": [r for r in rows if r["kind"] == "dispatched"
                                                           and r["at"] >= cutoff]}


def record(main: str, args) -> dict:
    if not args.argv:
        raise SystemExit("checks: the command to dispatch goes after `--`")
    keys = {"pane": args.pane or None, "title": args.title, "argv": args.argv,
            "cwd": str(Path(args.cwd or args.repo).resolve())}
    if args.checks == "defer":
        return checks.append(main, "deferred", args.slot, id=checks.new_id(args.slot), **keys)
    line = checks.append(main, "dispatched", args.slot, id=checks.new_id(args.slot), by="ci-check", run=args.run,
                         url=args.url, **keys)
    checks.supersede_older(main, checks.lines(main), args.slot, line["id"])  # the session's own dispatch is newer
    return line


def main(args, status, wiring: roles.Wiring) -> int:
    """`args.argv`: what followed `--`. `status(repo)` is tollman.status."""
    main_dir = mtm_scan.main_checkout(args.repo)
    if args.checks == "busy":
        r = busy_report(args.repo, status, wiring)
        text = (f"busy: {r['reason']}" if r["busy"] else "free") + ("\nlive" if r["live"]
                                                                  else f"\nnot live: {r['live_why']}")
        print(json.dumps(r) if args.json else text)
        return 0
    if args.checks in ("defer", "dispatched"):
        line = record(main_dir, args)
        print(json.dumps(line) if args.json else line["id"])
        return 0
    if args.checks == "list":
        d = listing(main_dir)
        print(json.dumps(d, indent=1) if args.json else "\n".join(
            [f"waits {e['slot']}: {e.get('title')} ({e['at']})" for e in d["pending"]]
            + [f"runs {e['slot']}: {e.get('title')} {e.get('url') or ''}" for e in d["dispatched"]]) or "nothing held")
        return 0
    code, text = (cancel(main_dir, args.run) if args.checks == "cancel" else dispatch(main_dir, args.id))
    print(json.dumps({"exit": code, "text": text}) if args.json else text)
    return code
