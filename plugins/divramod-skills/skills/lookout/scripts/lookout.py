#!/usr/bin/env python3
"""lookout: the global watch store and scheduler (hal2 plan 0311). This file is the CLI.

    lookout.py start [--dry-run]   install the 5-minute timer (launchd on macOS, a systemd user timer on Linux)
    lookout.py stop [--dry-run]    remove it
    lookout.py status [--json]     the timer, the last tick, "lookout not running since <time>" when it stopped

The timer is the farmer's `timer.py` with the Wiring below (D1, D14): the label `local.lookout.global`, `*/5 * * * *`
(minutes 0, 5, ... 55), the store folder as its working directory and the state folder for `tick.log`, `timer.json`,
`mode` and the tick's `heartbeat`. Windows (D8): timer.py has no Windows path, so `start` and `stop` say so and exit 2;
the gap is recorded in plans/0311-lookout/steps/5.md. The store commands and the tick live in `lookout_cmds.py`:

    lookout.py add|set|end|list|log|finds|run|tick   see `lookout.py <command> -h`

The tick ignores timer.py's `--repo <top>` (lookout is global, not per repo).
"""

import argparse
import datetime as dt
import json
import platform
import sys
from pathlib import Path

import lookout_frame  # noqa: F401  (puts the farmer's scripts on the import path: first)
import lookout_cmds
import paths
import roles
import timer

NAME = "global"
CRON = "*/5 * * * *"
STALE = dt.timedelta(minutes=15)  # a heartbeat older than this: the timer is not ticking
WINDOWS_GAP = ("lookout's timer has no Windows path yet: the farmer's timer.py knows launchd and systemd only "
               "(plan 0311 D8). Until a scheduled task exists run `schtasks /Create /SC MINUTE /MO 5 /TN "
               "local.lookout.global /TR \"python lookout.py tick\"` by hand.")

WIRING = roles.Wiring(
    role="lookout", cli=Path(__file__).resolve(), skill=Path(__file__).resolve().parents[1],
    act="", handoff="", duties=(), subskills={},
    env=("LOOKOUT_DIR", "LOOKOUT_STATE_DIR", "LOOKOUT_DAYBOOK", "XDG_CONFIG_HOME", "XDG_STATE_HOME"))


def heartbeat_at(state):
    """When the last tick ran: the heartbeat file's ISO time, else its mtime; None before the first tick."""
    f = Path(state) / "heartbeat"
    try:
        text = f.read_text(encoding="utf-8").strip()
        mtime = f.stat().st_mtime
    except OSError:
        return None
    try:
        at = dt.datetime.fromisoformat(text)
    except ValueError:
        at = dt.datetime.fromtimestamp(mtime)
    return at if at.tzinfo else at.astimezone()


def rendered(top, state, dry_cmds):
    """What `start --dry-run` prints: the unit file(s) it would write and the commands it would run."""
    if platform.system() == "Darwin":
        units = {timer.files(NAME, WIRING)[0]: timer.plist(NAME, top, state, CRON, WIRING)}
    else:
        units = dict(zip(timer.files(NAME, WIRING), timer.systemd(NAME, top, state, CRON, WIRING)))
    parts = [f"# {path}\n{text}" for path, text in units.items()]
    return "\n".join(parts + [" ".join(c) for c in dry_cmds])


def cmd_start(args):
    top, state = str(paths.config_root()), paths.state_root()
    if args.dry_run:
        print(rendered(top, state, timer.install(NAME, top, state, CRON, True, WIRING)))
        return 0
    for folder in (paths.config_root(), state):
        folder.mkdir(parents=True, exist_ok=True)
    try:
        timer.install(NAME, top, state, CRON, False, WIRING)
    except (RuntimeError, ValueError) as e:
        print(f"lookout.py: {e}", file=sys.stderr)
        return 2
    print(f"start: {timer.label(NAME, WIRING)} every 5 minutes")
    return 0


def cmd_stop(args):
    state = paths.state_root()
    if not args.dry_run:
        state.mkdir(parents=True, exist_ok=True)
    cmds = timer.remove(NAME, state, args.dry_run, WIRING)
    print("\n".join(" ".join(c) for c in cmds) if args.dry_run else f"stop: {timer.label(NAME, WIRING)} removed")
    return 0


def status(now=None):
    """The timer's state plus the heartbeat: `running` is true when the last tick is under 15 minutes old."""
    state, now = paths.state_root(), now or paths.now()
    info = timer.status(NAME, state, WIRING)
    beat = heartbeat_at(state)
    info["heartbeat"] = beat.isoformat() if beat else None
    info["running"] = bool(beat and now - beat <= STALE)
    return info


def status_line(info):
    head = f"{info['label']}: {'loaded' if info['loaded'] else 'not loaded'}, cron {info.get('cron', '-')}"
    if info["running"]:
        return f"{head}; last tick {info['heartbeat']}"
    if info["heartbeat"]:
        return f"{head}; lookout not running since {info['heartbeat']}"
    return f"{head}; lookout has not ticked yet"


def cmd_status(args):
    info = status()
    print(json.dumps(info, indent=1) if args.json else status_line(info))
    return 0


def windows_guard(_args):
    print(f"lookout.py: {WINDOWS_GAP}", file=sys.stderr)
    return 2


# name -> (help, add_arguments, run); the store commands and `tick` come from lookout_cmds.
COMMANDS = {
    "start": ("install the 5-minute timer", lambda p: p.add_argument("--dry-run", action="store_true"), cmd_start),
    "stop": ("remove the timer", lambda p: p.add_argument("--dry-run", action="store_true"), cmd_stop),
    "status": ("the timer and the last tick", lambda p: p.add_argument("--json", action="store_true"), cmd_status),
    **lookout_cmds.COMMANDS,
}
NEEDS_TIMER = ("start", "stop")


def parser():
    ap = argparse.ArgumentParser(prog="lookout.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, (text, add, _run) in COMMANDS.items():
        add(sub.add_parser(name, help=text))
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    if args.cmd in NEEDS_TIMER and platform.system() == "Windows":
        return windows_guard(args)
    return COMMANDS[args.cmd][2](args)


if __name__ == "__main__":
    sys.exit(main())
