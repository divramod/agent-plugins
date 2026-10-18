#!/usr/bin/env python3
"""Restart every running Claude session in place by `hal2-cli-agents restart --all --json`.

  restart.py [--dry-run] [--except PANE]... [--wait SECONDS]

The flags are passed through. Prints a table (project/slot, pane, action, result) and, for skipped sessions, the
reason. Exit 0 when nothing failed, 1 when a session failed or timed out, 2 when hal2-cli-agents is missing.
This session's own restart is done by the CLI's detached child, last.
"""
import argparse
import json
import shutil
import subprocess
import sys

BAD = {"failed", "timeout"}


def table(rows: list[dict]) -> list[str]:
    lines = [f"{'project/slot':<28} {'pane':<8} {'action':<22} result"]
    for r in rows:
        name = f"{str(r.get('project', '')).rstrip('/').rsplit('/', 1)[-1]}/{r.get('slot', '')}"
        result = r.get("result") or "-"
        if r.get("action") == "skip" and r.get("reason"):
            result = f"{result} ({r['reason']})"
        lines.append(f"{name:<28} {str(r.get('pane_id', '')):<8} {str(r.get('action', '')):<22} {result}")
    return lines


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--except", dest="skip", action="append", default=[], metavar="PANE")
    p.add_argument("--wait", metavar="SECONDS")
    a = p.parse_args(argv)
    if not shutil.which("hal2-cli-agents"):
        print("restart.py: hal2-cli-agents is missing: run scripts/install-prerequisites.sh (needs hal2)", file=sys.stderr)
        return 2
    cmd = ["hal2-cli-agents", "restart", "--all", "--json"]
    if a.dry_run:
        cmd.append("--dry-run")
    for pane in a.skip:
        cmd += ["--except", pane]
    if a.wait:
        cmd += ["--wait", a.wait]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        rows = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"restart.py: {' '.join(cmd[:3])} failed: {(r.stderr or r.stdout).strip()}", file=sys.stderr)
        return 1
    print("\n".join(table(rows)))
    if not a.dry_run and any(x.get("action") == "caller-last" for x in rows):
        print("This session restarts last, in about a minute.")
    return 1 if r.returncode != 0 or any(x.get("result") in BAD for x in rows) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
