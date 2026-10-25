#!/usr/bin/env python3
"""find-and-fix-vulnerabilities: the one command. collect -> report (enrich, rank, table) -> with --plan the planwriter.
Read-only until --plan (without --dry-run) writes the fix plan. Exit 0, 2 on bad arguments or input."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cache  # noqa: E402
import collect  # noqa: E402
import planwriter  # noqa: E402
import report as report_mod  # noqa: E402
import table  # noqa: E402
from run import Runner  # noqa: E402


def parse_args(argv):
    p = argparse.ArgumentParser(prog="scan.py", description=__doc__)
    p.add_argument("--root", default="~/a", help="the folder of the farms (default ~/a)")
    p.add_argument("--only", default=",".join(collect.PARTS), help="comma list of: " + ", ".join(collect.PARTS))
    p.add_argument("--worktree", help="scan this worktree instead of its repository's main checkout")
    p.add_argument("--servers-config", help="servers.toml (default: vulns/servers.toml in the hal2 config folder)")
    p.add_argument("--vm-mount", action="append", default=[], metavar="NAME=PATH")
    p.add_argument("--image", action="append", default=[], metavar="IMAGE", help="scan only this image")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="caches only, no network")
    mode.add_argument("--online", action="store_true", help="also look unknown severities up at OSV")
    p.add_argument("--all", action="store_true", help="also show outdated packages without a vulnerability id (brew)")
    p.add_argument("--json", action="store_true", help="print the enriched JSON instead of the table")
    p.add_argument("--plan", action="store_true", help="write one fix plan from the findings")
    p.add_argument("--repo", default=".", help="the repository the plan goes into (default: cwd)")
    p.add_argument("--dry-run", action="store_true", help="with --plan: print the plan, write nothing")
    return p.parse_args(argv)


def main(argv=None, runner=None, fetch=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    cargs = ["--root", args.root, "--only", args.only]
    for flag, val in (("--worktree", args.worktree), ("--servers-config", args.servers_config)):
        cargs += [flag, val] if val else []
    for m in args.vm_mount:
        cargs += ["--vm-mount", m]
    for i in args.image:
        cargs += ["--image", i]
    try:
        cargv = collect.parse_args(cargs)
    except SystemExit:
        return 2
    found = collect.run_all(runner or Runner(), cargv)
    out = report_mod.build(found, args.offline, args.online, fetch or cache.http_get, show_all=args.all)
    print(json.dumps(out, indent=2) if args.json else table.render(out["rows"], out["errors"], out["skipped"], out["hidden_outdated"]))
    if args.plan:
        try:
            print(planwriter.write_plan(out, Path(args.repo).expanduser().resolve(), args.dry_run))
        except (OSError, ValueError, RuntimeError) as e:
            print(f"scan.py: {e}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
