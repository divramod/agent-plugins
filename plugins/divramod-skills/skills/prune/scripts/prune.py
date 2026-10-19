#!/usr/bin/env python3
"""prune.py: /prune's script (hal2 plan 0377; contract: plans/0377-prune/design/prune-run/sequence/v1/contract.md).

  prune.py plan [--json] [--cached-sizes] [--field NN]... [--repo DIR]
      the facts and the planned actions per job, nothing changed; sizes come from the cache when HEAD and mtime match;
      `--cached-sizes`: cache hits only, a miss is unknown, no walk (a quick answer).
      Exit 0, 1 an unreadable tool answer or config, 2 a tool missing.
  prune.py run [--dry-run] [--field NN]... [--repo DIR]
      the plan carried out one field at a time (executor.py), printed as workflow commands for
      `hal2-cli-runs exec --workflow prune -- prune.py run`; `--dry-run` changes nothing ("would ...").
      Exit 0 done or another run holds the farm lock ("already running: ..."), 1 an action failed, 2 a tool missing.
"""

import argparse
import json
import sys

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import executor
import facts
import mtm_scan
import plan as planner


def cmd_plan(args) -> int:
    main = mtm_scan.main_checkout(args.repo)
    only = set(args.field) or None
    found = facts.collect(main, only=only, cached_sizes=args.cached_sizes)
    p = planner.plan(found, only)
    if args.json:
        print(json.dumps({"plan": p, "facts": {k: found[k] for k in ("main", "disk", "config", "cars", "fields")}},
                         indent=2))
    else:
        print("\n".join(["facts:", *(f"  {planner.field_line(f)}" for f in found["fields"]), *planner.lines(p)]))
    return 0


def cmd_run(args) -> int:
    return executor.run(mtm_scan.main_checkout(args.repo), set(args.field) or None, args.dry_run)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="prune.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="show the facts and the planned actions")
    p.add_argument("--json", action="store_true")
    p.add_argument("--cached-sizes", action="store_true", help="sizes from the cache only (a miss is unknown), no walk")
    r = sub.add_parser("run", help="carry the plan out, as workflow commands")
    r.add_argument("--dry-run", action="store_true", help="change nothing, say what would be done")
    for x in (p, r):
        x.add_argument("--field", action="append", default=[], metavar="NN", help="only this field (repeatable)")
        x.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    if missing := facts.missing_tools():
        print(f"prune: not installed: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        return cmd_run(args) if args.cmd == "run" else cmd_plan(args)
    except facts.ToolMissing as e:
        print(f"prune: not installed: {e}", file=sys.stderr)
        return 2
    except facts.FactsError as e:
        print(f"prune: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
