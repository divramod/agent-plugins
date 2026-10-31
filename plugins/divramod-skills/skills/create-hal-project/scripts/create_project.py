#!/usr/bin/env python3
"""Set up a new hal project through `hal2-cli-projects new` (plan 0470 step 8; the logic moved into hal2-projects).

  create_project.py <name> <alias> [--dry-run] [--json] [--owner OWNER] [--smug a.yml,b.yml,...]

Plans first (`new plan`, nothing changes), then acts (`new apply --yes`, only without --dry-run); the CLI makes the
private GitHub repo, the checkout in the first root (~/a), the hal layout, the pre-push hook and the smug windows,
idempotent and never overwriting. This script only maps the old arguments and passes the CLI's answer on.
Exit codes are the CLI's: 1 failed, 2 gh or git missing / usage, 3 not found, 10 plan changed, 12 gh missing, 13 not logged in.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

CLI = "hal2-cli-projects"


def command(a: argparse.Namespace) -> list[str]:
    verb = ["new", "plan"] if a.dry_run else ["new", "apply"]
    argv = [CLI, *verb, a.name, "--alias", a.alias, "--kind", "github"]
    if a.owner:
        argv += ["--owner", a.owner]
    for yml in (f for f in (a.smug or "").split(",") if f):
        argv += ["--smug", yml]
    if not a.dry_run:
        argv.append("--yes")
    if a.json:
        argv.append("--json")
    return argv


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("name")
    p.add_argument("alias")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--owner", default="", help="GitHub owner (default: the login gh acts as)")
    p.add_argument("--smug", default="", help="comma-separated ymls in ~/.config/smug (default: the six)")
    a = p.parse_args()
    if not shutil.which(CLI):
        print(f"create_project.py: {CLI} is not installed yet (hal2 plan 0470)", file=sys.stderr)
        return 2
    return subprocess.run(command(a)).returncode


if __name__ == "__main__":
    sys.exit(main())
