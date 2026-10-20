"""plan.py's commands of the one plan shape (hal2 plan 0376, row 7): `subplan new`, `step add` and `overview`, on a
plan folder of schema 2 (one with `subplans/`); a plan of schema 1 or legacy is refused with the hint to convert it.

  plan.py subplan new "<title>" [--goal "<goal>"] [--wave <n>] [--plan <slug>]
  plan.py step add <subplan> "<title>" [--done-when "<check>"] [--wave <n>] [--model m] [--effort e] [--window w]
                   [--size s] [--plan <slug>]
  plan.py overview [--write | --check] [--plan <slug>]
  plan.py subplan start|finish <NN> [--plan <slug>]   the side branch <field>-<NN> (row 8, design A9: shape_git.py)
"""
from __future__ import annotations

from pathlib import Path

import shape
import shape_git
import shape_new
import shape_overview
import sizing

COMMANDS = ("subplan", "step", "overview")


def add_parsers(sub) -> None:
    p_subplan = sub.add_parser("subplan", help="a sub-plan of a plan in the new shape")
    subplan_sub = p_subplan.add_subparsers(dest="action", required=True)
    p_new = subplan_sub.add_parser("new", help="the next work sub-plan NN-<slug>, its wave one above the highest")
    p_new.add_argument("title")
    p_new.add_argument("--goal", default="", help="its goal; its first sentence is the deliverable")
    p_new.add_argument("--wave", type=int, help="join this wave instead of opening the next")
    p_new.add_argument("--plan")
    for action, does in (("start", "switch to the side branch <field>-<NN> (made from <field> when missing)"),
                         ("finish", "its steps done: switch back to <field> and merge <field>-<NN> --no-ff")):
        p_git = subplan_sub.add_parser(action, help=does)
        p_git.add_argument("number", help="the sub-plan: its number (2, 02) or folder (02-readers)")
        p_git.add_argument("--plan")
    p_step = sub.add_parser("step", help="a step of a sub-plan in the new shape")
    step_sub = p_step.add_subparsers(dest="action", required=True)
    p_add = step_sub.add_parser("add", help="the next step of a work sub-plan, its wave one above the highest")
    p_add.add_argument("subplan", help="the sub-plan: its number (2, 02) or folder (02-readers)")
    p_add.add_argument("title")
    p_add.add_argument("--done-when", default="", help="the step's done-when, its `description`")
    p_add.add_argument("--task", default="", help="the step's task, its `## Task`")
    p_add.add_argument("--wave", type=int, help="join this wave instead of opening the next")
    p_add.add_argument("--model", choices=sizing.MODELS)
    p_add.add_argument("--effort", choices=sizing.EFFORTS)
    p_add.add_argument("--window", choices=list(sizing.WINDOWS))
    p_add.add_argument("--size", help="the estimated peak context, e.g. 150k")
    p_add.add_argument("--plan")
    p_overview = sub.add_parser("overview", help="plan.md's generated overview of a plan in the new shape")
    mode = p_overview.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="regenerate it (hal2-cli-plans when it can, else shape.py)")
    mode.add_argument("--check", action="store_true", help="exit 1 when it or a derived status is stale")
    p_overview.add_argument("--plan")


def run(root: Path, path: Path, args) -> tuple[dict | str, int]:
    """The command's JSON (or the overview's text) and exit code for the plan whose plan.md is `path`."""
    folder = path.parent
    if args.command == "subplan" and args.action in ("start", "finish"):
        return (shape_git.start if args.action == "start" else shape_git.finish)(root, folder, args.number), 0
    if args.command == "subplan":
        return shape_new.add_subplan(root, folder, args.title, args.goal, args.wave), 0
    if args.command == "step":
        sized = {"model": args.model, "effort": args.effort, "window": args.window, "size": args.size}
        return shape_new.add_step(root, folder, args.subplan, args.title, args.wave, args.done_when, sized,
                                  args.task), 0
    if args.write:
        return {"plan": folder.name, "overview": shape.write_overview(root, folder)}, 0
    if args.check:
        stale = shape.check_overview(folder)
        return {"plan": folder.name, "stale": stale}, 1 if stale else 0
    return shape_overview.render(shape.load(folder)), 0
