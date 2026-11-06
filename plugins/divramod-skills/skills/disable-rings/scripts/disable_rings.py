#!/usr/bin/env python3
"""/disable-rings: set or show the ring switch through `hal2-cli-ring mode --json` (plan 0606, D12).

Calls: (none) = off; silent [--for D]; off [--for D]; on (= ring); status; h|help.
Exit 0 ok, 1 the CLI refused, 2 hal2-cli-ring missing, 64 bad call.
"""
import json
import shutil
import subprocess
import sys

CLI = "hal2-cli-ring"
FROM = "disable-rings"

HELP = """/disable-rings: mute the iPhone ring (every ring obeys the switch, --force too)
| Call | Does |
|---|---|
| `/disable-rings` | same as `off`: no Find My call at all until `on` |
| `/disable-rings off [--for 2h]` | no Find My call; with `--for` it ends by itself (30m, 2h, 1h30m, 1d; at most 30d) |
| `/disable-rings silent [--for 2h]` | the message on the iPhone without the alert sound |
| `/disable-rings on` | the way back: `ring`, with sound |
| `/disable-rings status` | the switch now and when it ends |
| `/disable-rings h`, `/disable-rings help` | print this table |
"""

POSITIONS = {"off": "off", "silent": "silent", "on": "ring", "ring": "ring"}


def parse(args):
    """Return (position or None for status, for-duration or None), or raise ValueError."""
    if not args:
        return "off", None
    word, rest = args[0], args[1:]
    if word == "status":
        if rest:
            raise ValueError("status takes no arguments")
        return None, None
    if word not in POSITIONS:
        raise ValueError(f"unknown call {word!r}")
    duration = None
    if rest:
        if len(rest) == 2 and rest[0] == "--for":
            duration = rest[1]
        elif len(rest) == 1 and rest[0].startswith("--for="):
            duration = rest[0][len("--for="):]
        else:
            raise ValueError(f"unexpected arguments {' '.join(rest)!r}")
    if duration and POSITIONS[word] == "ring":
        raise ValueError("--for goes only with silent or off")
    return POSITIONS[word], duration


def line(state):
    mode, until = state["mode"], state.get("until")
    if mode == "ring":
        return "ring: rings with sound"
    what = "no Find My call" if mode == "off" else "the message without sound"
    end = f"until {until}" if until else "until changed"
    return f"{mode} {end}: {what}. Back: /disable-rings on"


def main(argv):
    if argv and argv[0] in ("h", "help", "--help", "-h"):
        print(HELP, end="")
        return 0
    try:
        position, duration = parse(argv)
    except ValueError as err:
        print(f"disable-rings: {err}\n", file=sys.stderr)
        print(HELP, end="", file=sys.stderr)
        return 64
    if shutil.which(CLI) is None:
        print(f"disable-rings: {CLI} is not installed yet (cargo install --path code/rust/apps/{CLI})",
              file=sys.stderr)
        return 2
    cmd = [CLI, "mode"]
    if position:
        cmd.append(position)
        if duration:
            cmd += ["--for", duration]
        cmd += ["--from", FROM]
    cmd.append("--json")
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        print((done.stderr or done.stdout).strip() or f"{CLI} failed", file=sys.stderr)
        return 1
    try:
        print(line(json.loads(done.stdout)))
    except (ValueError, KeyError):
        print(f"disable-rings: unreadable output of {CLI}: {done.stdout.strip()[:200]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
