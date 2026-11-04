"""board.py's commands (`post`, `list`, `sync`; split out of board.py by hal2 plan 0610 step 9, small-files): board.py's
module doc names them; board.main calls this."""

import argparse
import json
import os
import sys

import board
import mtm_scan


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=board.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    post_p, list_p = sub.add_parser("post"), sub.add_parser("list")
    sync_p = sub.add_parser("sync")
    post_p.add_argument("--kind", required=True)
    post_p.add_argument("--from", dest="frm", required=True)
    post_p.add_argument("--to", required=True)
    for key in ("text", "id", "run", "head", "status", "train", "commit"):
        post_p.add_argument(f"--{key}")
    post_p.add_argument("--cars", type=lambda s: [c for c in s.split(",") if c])
    list_p.add_argument("--kind")
    list_p.add_argument("--last", type=int)
    list_p.add_argument("--json", action="store_true")
    for x in (post_p, list_p, sync_p):
        x.add_argument("--repo", default=os.getcwd())
        x.add_argument("--role", default=board.ROLE, choices=board.ROLES)
    a = p.parse_args(argv)
    main_dir = mtm_scan.main_checkout(a.repo)
    try:
        if a.cmd == "post":
            keys = {k: getattr(a, k) for k in board.KEYS if hasattr(a, k)}
            print(json.dumps(board.post(main_dir, a.kind, a.frm, a.to, role=a.role, **keys)))
        elif a.cmd == "sync":
            print(f"{len(board.sync(main_dir, a.role))} lines posted")
        else:
            rows = board.lines(main_dir, a.kind, a.last, a.role)
            print(json.dumps(rows, indent=1) if a.json else "\n".join(
                f"{r['at']} {r['kind']:9} {r['from']} -> {r['to']}: {r.get('text', '')[:100]}" for r in rows)
                or "the board is empty")
    except (ValueError, OSError) as e:
        print(f"board.py: {e}", file=sys.stderr)
        return 1
    return 0
