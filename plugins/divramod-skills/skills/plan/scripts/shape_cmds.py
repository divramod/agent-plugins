"""plan.py's step commands routed to the one plan shape (hal2 plan 0376, row 8): on a plan folder with `subplans/`,
`status`, `current`, `trailers`, `prompt`, `ready`, `assign` and `uat add` run here (shape_status, shape_ready,
shape_prompt, shape_uat); every other plan keeps plan.py's own code. `subplan start|finish` are shape_cli's,
`check`'s schema 2 rules shape_check's.

  plan.py status <ref> <status> [--why <text>]     the step file's status, then the overview (a ref `01.03`)
  plan.py current                                  derived status, work steps done/total, next ref and sub-plan
  plan.py trailers [<ref>]                          Worktree, Plan, Step: <ordinal>/<work steps>
  plan.py prompt <ref> [--part k] [--model m] [--effort e]   the hand's Agent call
  plan.py ready [--json] [--limit n]               both levels by `schedule`, D19's who
  plan.py assign <NN> <who>                        the sub-plan's `who`: foreman, field NN, - (none)
  plan.py uat add "<title>" [--steps ...] [--expected ...] [--open ...] [--run ...] [--priority p1-p3]
                  [--kind scripted|explore] [--tags a,b]   one check in subplans/99-uat/steps/
"""
from __future__ import annotations

from pathlib import Path

import shape
import shape_lead
import shape_prompt
import shape_ready
import shape_status
import shape_uat
from shape_names import ShapeError

ROUTED = ("status", "current", "trailers", "prompt", "ready", "assign", "uat")


def uat_args(p_uat) -> None:
    """`uat add <title>` and its check fields beside `uat`'s own `--plan` and `--shotfile`."""
    p_uat.add_argument("action", nargs="?", choices=["add"], help="add: one check (a plan of schema 2)")
    p_uat.add_argument("title", nargs="?", default="")
    p_uat.add_argument("--steps", nargs="+", default=[], help="the check's steps, one argument each")
    p_uat.add_argument("--expected", default="", help="what the user sees when it passes (its description)")
    p_uat.add_argument("--open", default="", help="the link the check opens (`hal9k://...`)")
    p_uat.add_argument("--run", default="", help="the command the check runs")
    p_uat.add_argument("--priority", default="p2")
    p_uat.add_argument("--kind", default="scripted")
    p_uat.add_argument("--tags", default="", help="comma-separated tags (`smoke`)")


def routed(path: Path, command: str) -> bool:
    """Whether `command` on the plan file `path` runs here: a plan.md in a folder with `subplans/`."""
    return command in ROUTED and path.name == "plan.md" and shape.is_shape(path.parent)


def uat_fields(args) -> dict:
    return {"steps": args.steps, "expected": args.expected, "open": args.open, "run": args.run,
            "priority": args.priority, "kind": args.kind, "tags": [t.strip() for t in args.tags.split(",") if t.strip()]}


def run(root: Path, path: Path, args, describe) -> tuple[dict | str, int]:
    """The command's JSON (or text) and exit code; `describe(path)` is plan.py's describe of the plan."""
    folder, command = path.parent, args.command
    lead = shape_lead.lead(root, folder.name)
    if command == "trailers":
        return "\n".join(shape_status.trailer_lines(root, folder, args.step)) + "\n", 0
    if command == "prompt":
        at = shape_status.ref(shape.load(folder), args.step)
        return shape_prompt.call(root, folder, at, args.part, args.model, args.effort), 0
    if command == "ready":
        result = shape_ready.ready(root, folder, args.limit, lead)
        return (result if args.json else "\n".join(shape_ready.lines(result)) + "\n"), 0
    if command == "assign":
        return shape_status.assign(root, folder, args.step, args.who), 0
    if command == "uat":
        if args.action != "add":
            raise ShapeError("a plan of schema 2 has no uat.md: `plan.py uat add \"<title>\"` adds a 99-uat check")
        return shape_uat.add(root, folder, args.title, uat_fields(args)), 0
    written = None
    if command == "status":
        written = shape_status.set_status(root, folder, args.step, args.status, args.why, lead)
    result = shape_status.current(folder, describe(path))
    return ({**result, "written": written} if written else result), 0
