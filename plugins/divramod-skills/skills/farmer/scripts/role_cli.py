"""What every role's command line shares over the round frame (hal2 plan 0294, step 5): the start check, a tick
behind its lock and its mode gate, the timer, the wake items and the handoff. `farmer.py` and the tollman
skill's `tollman.py` call these with their own `roles.Wiring` and handlers, so neither copies the other.

State: the role's state folder (`roles/<role>/` of its field `<role>-<repo>`, roles.state_dir). Exit codes as
farmer.py names them: 0 ok (also `busy`), 1 an invalid role file, 2 a tool missing, 3 no role file, 4 not the
role's field, a field holding other work, or not in timer mode.
"""

import datetime
import fcntl
import json
import shutil
import sys
from pathlib import Path

import due
import handoff
import roles
import silence
import tick
import timer
import wake

TOOLS = ("git", "gh", "hal2-cli-git", "hal2-cli-agents")
MODES = ("claude", "timer")


def state(repo: str, wiring: roles.Wiring) -> Path:
    return roles.state_dir(repo, due.DATA, wiring.role)


def mode(repo: str, wiring: roles.Wiring) -> str:
    f = state(repo, wiring) / "mode"
    text = f.read_text().strip() if f.exists() else ""
    return text if text in MODES else "claude"


def set_mode(repo: str, wiring: roles.Wiring, value: str) -> None:
    (state(repo, wiring) / "mode").write_text(value + "\n")


def missing() -> list[str]:
    return [t for t in TOOLS if not shutil.which(t)]


def start_check(repo: str, wiring: roles.Wiring) -> tuple[int, dict]:
    """May the role start here? Its tools, its field holding nothing but its role files, a valid role file."""
    gone = missing()
    if gone:
        return 2, {"ok": False, "problems": [f"missing {', '.join(gone)}: run "
                                             f"{wiring.cli.parent}/install-prerequisites.sh"]}
    problem = tick.slot_problem(repo, wiring)
    if problem:
        return 4, {"ok": False, "problems": [problem]}
    top = tick.toplevel(repo)
    role = Path(top) / wiring.role_file
    if not role.exists():
        hint = " (template: templates/ROLE.md)" if (wiring.skill / "templates/ROLE.md").exists() else ""
        return 3, {"ok": False, "problems": [f"no {role}: nothing is opted in{hint}"]}
    items, settings, problems = due.schedule(role.read_text(), wiring.duties)
    if problems:
        return 1, {"ok": False, "problems": problems}
    return 0, {"ok": True, "loop_cron": due.loop_cron(items), "settings": settings, "mode": mode(top, wiring),
               "items": sorted(items)}


def print_start_check(code: int, result: dict, as_json: bool) -> int:
    print(json.dumps(result, indent=1) if as_json else
          (f"ok: loop cron `{result['loop_cron']}`, mode {result['mode']}" if result["ok"] else
           "\n".join(f"- {x}" for x in result["problems"])))
    return code


def print_round(r: dict, wiring: roles.Wiring) -> None:
    head, role = "dry run" if r["dry"] else "round", wiring.role
    if r.get("problem"):
        print(f"{role} tick ({head}): {r['problem']}")
        return
    print(f"{role} tick ({head}): {len(r.get('due', []))} due"
          + (f": {', '.join(i['name'] for i in r['due'])}" if r.get("due") else ""))
    for a in r["planned"]:
        what = a.get("text") or " ".join(a.get("argv", [])) or a.get("name", "")
        print(f"- {a['do']:6} {a['duty']}/{a['kind']} {a['slot']}: {what}")
    for key in ("relay", "delegate", "wake", "notify"):
        if r.get(key):
            print(f"{key}: " + "; ".join(a.get("text", "") for a in r[key]))
    if r.get("woke"):
        w = r["woke"]
        print(f"wake: {w['pending']} pending" + (f", {role} woken" if w["woken"] else f" ({w['why']})" if w.get("why")
                                                 else ""))
    if r.get("summary"):
        print(f"summary: {r['summary']}")
    if r.get("timing"):
        print(tick.timing_line(r["timing"], r.get("gh")))


def run_tick(repo: str, dry: bool, as_json: bool, handlers: dict, wiring: roles.Wiring, all_due: bool = False,
             silent_lines=None) -> int:
    """One round behind the role's tick lock; outside a dry run only in timer mode. A silenced role (silence.py)
    prints table lines only: `silent_lines(r, wiring)` or the default one line."""
    cli, gone = wiring.cli.name, missing()
    if gone:
        print(f"{cli}: missing {', '.join(gone)}; run {wiring.cli.parent}/install-prerequisites.sh", file=sys.stderr)
        return 2
    if not dry and mode(repo, wiring) != "timer":
        print(f"{cli}: mode is `claude` (the {wiring.role}'s Claude loop runs the rounds); a tick runs only in timer "
              f"mode (`{cli} mode timer`), or use --dry-run", file=sys.stderr)
        return 4
    if all_due and not dry:
        print(f"{cli}: --all-due only measures: use it with --dry-run", file=sys.stderr)
        return 4
    with (state(repo, wiring) / "tick.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("busy: another tick runs")
            return 0
        timer.rotate(state(repo, wiring))
        r = tick.run(repo, dry, handlers, all_due=all_due, wiring=wiring)
        if not dry and not r.get("problem"):
            follow_cron(repo, wiring)
    print(json.dumps(r, indent=1, default=str) if as_json else "", end="")
    if not as_json and not dry and silence.on(repo, wiring):
        print("\n".join((silent_lines or silence.round_lines)(r, wiring)))
    elif not as_json:
        print_round(r, wiring)
    return 4 if r.get("problem") else 0


def follow_cron(repo: str, wiring: roles.Wiring) -> None:
    """Reinstall the timer when the role file changed the loop's cron."""
    code, check = start_check(repo, wiring)
    st = state(repo, wiring)
    if code == 0 and timer.installed(st).get("cron") not in (None, check["loop_cron"]):
        timer.install(due.repo_name(repo), tick.toplevel(repo), st, check["loop_cron"],
                      wiring=wiring)
        print(f"timer: loop cron now {check['loop_cron']}")


def run_timer(args, wiring: roles.Wiring) -> int:
    st, name = state(args.repo, wiring), due.repo_name(args.repo)
    if args.action == "status":
        r = timer.status(name, st, wiring) | {"mode": mode(args.repo, wiring)}
        print(json.dumps(r, indent=1) if args.json else
              f"{r['label']}: {'loaded' if r['loaded'] else 'not loaded'}, cron {r.get('cron', '-')}, mode {r['mode']}")
        return 0
    if args.action == "remove":
        cmds = timer.remove(name, st, args.dry_run, wiring)
    else:
        code, check = start_check(args.repo, wiring)
        if code:
            print("\n".join(f"- {x}" for x in check["problems"]), file=sys.stderr)
            return code
        top = tick.toplevel(args.repo)
        try:
            cmds = timer.install(name, top, st, check["loop_cron"], args.dry_run, wiring)
        except (RuntimeError, ValueError) as e:
            print(f"{wiring.cli.name}: {e}", file=sys.stderr)
            return 2
    print("\n".join(" ".join(c) for c in cmds) if args.dry_run else f"{args.action}: mode {mode(args.repo, wiring)}")
    return 0


def run_wake(args, wiring: roles.Wiring) -> int:
    """What the tick handed to the role's session (wake.json); `--done <seq>` drops the items up to it."""
    main = tick.mtm_scan.main_checkout(args.repo)
    if args.done is not None:
        print(f"{wake.done(main, args.done, wiring)} items left")
        return 0
    data = wake.read(main, wiring)
    if handoff.path(main, wiring).exists() and not args.json:
        print(f"read first: {handoff.path(main, wiring)}")
    if args.json:
        print(json.dumps(data, indent=1))
        return 0
    for i in data["items"]:
        print(f"{i['seq']:3} {i['do']:6} {i['duty']}/{i['kind']} {i['slot']}: {i.get('text', '')}\n"
              f"    read {i['instructions']}")
    print(f"{len(data['items'])} items" + (f", woken {data['woken_at']}" if data.get("woken_at") else ""))
    return 0


def run_handoff(args, wiring: roles.Wiring) -> int:
    main = tick.mtm_scan.main_checkout(args.repo)
    if not args.clear:
        print(handoff.show(main, wiring))
        return 0
    top = tick.toplevel(args.repo) or args.repo
    code, what = handoff.clear(top, main, datetime.datetime.now(), wiring)
    print(what)
    return code
