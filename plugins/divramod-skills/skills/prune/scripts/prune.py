#!/usr/bin/env python3
"""prune.py: /prune's script (hal2 plan 0377; contract: plans/0377-prune/design/prune-run/sequence/v1/contract.md).

  prune.py plan [--json] [--cached-sizes] [--field NN]... [--repo DIR]
      the facts and the planned actions per job, nothing changed; sizes come from the cache when HEAD and mtime match;
      `--cached-sizes`: cache hits only, a miss is unknown, no walk (a quick answer).
      Exit 0, 1 an unreadable tool answer or config, 2 a tool missing.
  prune.py run [--dry-run] [--responses] [--field NN]... [--repo DIR]
      the plan carried out one field at a time (executor.py), printed as workflow commands for
      `hal2-cli-runs exec --workflow prune -- prune.py run`; `--dry-run` changes nothing ("would ...").
      `--responses`: only the disk watermark's responses (plan 0472 D2: `tart prune --entries caches`, the caches of
      `.hal/prune.toml`'s `[caches] paths`), when the disk is still above the goal and no train builds.
      Exit 0 done or another run holds the farm lock ("already running: ..."), 1 an action failed, 2 a tool missing.
      A run without `--field` and `--responses` starts with the disk phase (below).
  prune.py disk [--dry-run] [--due] [--json] [--repo DIR]
      the disk phase alone (disk_phase.py, plan 0514 D18): idle fields' `code/rust/target` deleted while the disk has
      less than `[disk] below_gb` free (80 GB), until `until_gb` (150 GB); never deferred by a workqueue hold, sized by
      the filesystem's free space (no `du`). `--due`: only say whether it is due (`--json`: `{due, free_gb, below_gb,
      until_gb, note}`), nothing changed. Exit 0 done, 1 a deletion failed, 2 git missing.
"""

import argparse
import json
import shutil
import sys

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import disk_phase
import executor
import facts
import mtm_scan
import plan as planner


def cmd_plan(args) -> int:
    main = mtm_scan.main_checkout(args.repo)
    only = set(args.field) or None
    found = facts.collect(main, only=only, cached_sizes=args.cached_sizes)
    p = planner.plan(found, only)
    for line in found.get("advice", []):
        print(f"prune: {line}", file=sys.stderr)
    if args.json:
        print(json.dumps({"plan": p, "facts": {k: found[k] for k in ("main", "busy", "disk", "config", "cars", "fields")}},
                         indent=2))
    else:
        print("\n".join(["facts:", *(f"  {planner.field_line(f)}" for f in found["fields"]), *planner.lines(p)]))
    return 0


def cmd_run(args) -> int:
    only = set() if args.responses else set(args.field) or None  # an empty set: no field, just the responses
    return executor.run(mtm_scan.main_checkout(args.repo), only, args.dry_run, responses_only=args.responses)


def cmd_disk(args) -> int:
    main = mtm_scan.main_checkout(args.repo)
    if args.due:
        state = disk_phase.due(main)
        print(json.dumps(state) if args.json else
              f"{'due' if state['due'] else 'fine'}: {state['free_gb']:g} GB free (mark {state['below_gb']:g} GB)")
        return 0
    rows = disk_phase.run(main, args.dry_run)
    return 1 if any(r["status"] == "failure" for r in rows) else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="prune.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="show the facts and the planned actions")
    p.add_argument("--json", action="store_true")
    p.add_argument("--cached-sizes", action="store_true", help="sizes from the cache only (a miss is unknown), no walk")
    r = sub.add_parser("run", help="carry the plan out, as workflow commands")
    r.add_argument("--dry-run", action="store_true", help="change nothing, say what would be done")
    r.add_argument("--responses", action="store_true", help="only the disk watermark's responses (tart cache, caches)")
    for x in (p, r):
        x.add_argument("--field", action="append", default=[], metavar="NN", help="only this field (repeatable)")
        x.add_argument("--repo", default=".")
    d = sub.add_parser("disk", help="the disk phase alone: idle fields' Rust build folders while the disk is low")
    d.add_argument("--dry-run", action="store_true", help="change nothing, say what would be deleted")
    d.add_argument("--due", action="store_true", help="only say whether the disk is below its mark")
    d.add_argument("--json", action="store_true")
    d.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    if args.cmd == "disk":
        if missing := [t for t in disk_phase.TOOLS if not shutil.which(t)]:
            print(f"prune: not installed: {', '.join(missing)}", file=sys.stderr)
            return 2
        try:
            return cmd_disk(args)
        except facts.FactsError as e:
            print(f"prune: {e}", file=sys.stderr)
            return 1
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
