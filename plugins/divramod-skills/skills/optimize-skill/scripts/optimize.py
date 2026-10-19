#!/usr/bin/env python3
"""optimize-skill's CLI (plan 0390 step 4): improve one skill by SkillOpt's loop under a hard token cap. Stdlib only.

    optimize.py init <skill-dir>                  reuse <skill-dir>/evals/evals.json (checked, counts per split),
                                                  else write the skeleton there for the session to draft (D2)
    optimize.py estimate <skill-dir> [opts]       the run's token estimate, no model call
    optimize.py run <skill-dir> [opts]            the loop (loop.py) into a run folder (runs.py), best.diff at the end
    optimize.py status [<skill>] [--run <id>]     the last run's report: scores baseline -> best, tokens, stop reason
    optimize.py diff <skill> [--run <id>]         print the run's best.diff (empty: nothing beat the baseline)
    optimize.py h | help                          this usage

Every command takes `--json`. `init` is the only command that writes into a skill's folder, and only a missing
`evals/evals.json`; `run` never does (the session shows best.diff and applies it on the user's word). The run
folder is `$OPTIMIZE_SKILL_HOME/<skill>/<run id>/` (default ~/.cache/hal2/optimize-skill), the claude binary
`$OPTIMIZE_SKILL_CLAUDE` (default `claude`). Exit 0 done, 1 a refused input or no run, 2 a usage error.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

import estimate as estimate_mod
import evalset
import loop
import runs

USAGE = __doc__.split("\n\n")[1]


def _run_opts(parser, full):
    parser.add_argument("--epochs", type=int, default=loop.DEFAULTS["epochs"])
    parser.add_argument("--candidates", type=int, default=loop.DEFAULTS["candidates"])
    parser.add_argument("--max-tokens", type=int, default=loop.DEFAULTS["max_tokens"])
    parser.add_argument("--max-rollouts", type=int, default=loop.DEFAULTS["max_rollouts"])
    parser.add_argument("--model", default=loop.DEFAULTS["model"], help="the rollouts' model")
    parser.add_argument("--optimizer-model", default=loop.DEFAULTS["optimizer_model"],
                        help="the reflection's and edit proposals' model")
    if full:
        parser.add_argument("--max-turns", type=int, default=loop.DEFAULTS["max_turns"])
        parser.add_argument("--timeout", type=int, default=loop.DEFAULTS["timeout"], help="seconds per rollout")
        parser.add_argument("--run-dir", help="the run folder (default: a new one under the run home)")
        parser.add_argument("--support", action="append", default=[], metavar="DEST[=SRC]",
                            help="also put SRC (a file or folder) at DEST in every rollout's workspace; "
                                 "no SRC: an empty folder")


def parser():
    top = argparse.ArgumentParser(prog="optimize.py", description="Improve one skill under a token cap.")
    sub = top.add_subparsers(dest="command", required=True)
    for name, helptext in (("init", "reuse or start the eval set"), ("estimate", "the token estimate"),
                           ("run", "run the optimize loop")):
        cmd = sub.add_parser(name, help=helptext)
        cmd.add_argument("skill_dir")
        if name != "init":
            _run_opts(cmd, name == "run")
    for name in ("status", "diff"):
        cmd = sub.add_parser(name, help=f"the last run's {'report' if name == 'status' else 'best.diff'}")
        cmd.add_argument("skill", nargs="?" if name == "status" else None)
        cmd.add_argument("--run", help="a run id (default: the last run)")
    for cmd in sub.choices.values():
        cmd.add_argument("--json", action="store_true", help="print JSON")
    return top


def _skill_dir(path):
    folder = Path(path).expanduser()
    if not (folder / "SKILL.md").is_file():
        raise loop.RunError(f"no SKILL.md in {folder}")
    return folder.resolve()


def cmd_init(args):
    folder = _skill_dir(args.skill_dir)
    path = evalset.evals_path(folder)
    if not path.exists():
        runs.write_json(path, evalset.skeleton(runs.skill_name(folder)))
        return 0, {"state": "written", "path": str(path)}, f"wrote the skeleton {path}: draft its evals, then rerun init"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    try:
        found = evalset.load(path)
    except evalset.EvalSetError as exc:
        return 1, {"state": "invalid", "path": str(path), "errors": exc.errors}, f"invalid {path}: {exc}"
    out = {"state": "skeleton" if evalset.is_skeleton(data) else "ready", "path": str(path),
           "train": len(found.train()), "val": len(found.val())}
    if out["state"] == "skeleton":
        return 0, out, f"{path} is still the skeleton: draft its prompts and checks"
    return 0, out, f"{path}: {out['train']} train + {out['val']} val evals, ready"


def cmd_estimate(args):
    found = evalset.load(_skill_dir(args.skill_dir))
    est = estimate_mod.estimate(len(found.train()), len(found.val()), epochs=args.epochs, candidates=args.candidates,
                                max_tokens=args.max_tokens, max_rollouts=args.max_rollouts, model=args.model,
                                optimizer_model=args.optimizer_model)
    return 0, est, estimate_mod.line(est)


def _support(items):
    out = {}
    for item in items:
        dest, _, src = item.partition("=")
        out[dest] = str(Path(src).expanduser().resolve()) if src else None
    return out or None


def summary(report):
    """The one-line form of a report."""
    base, best, stop = report.get("baseline") or {}, report.get("best") or {}, report.get("stop") or {}
    tokens = (report.get("tokens") or {}).get("spent", 0)
    scores = (f"val {base['val']:.3f} -> {best.get('val', base['val']):.3f}, train {base['train']:.3f} -> "
              f"{best.get('train', base['train']):.3f}" if "val" in base else "no baseline")
    head = f"{report['skill']} run {report['run_id']} ({report['state']}): {scores}"
    tail = (f"best {best.get('candidate')}, apply with: {report.get('apply')}" if report.get("improved")
            else "nothing beat the baseline")
    stopped = f"stop {stop['reason']} ({stop['detail']})" if stop else "running"
    return f"{head}; {stopped}; {tokens:,} tokens; {tail}"


def cmd_run(args):
    folder = _skill_dir(args.skill_dir)
    run_dir = Path(args.run_dir).expanduser() if args.run_dir else None
    if run_dir and run_dir.exists() and any(run_dir.iterdir()):
        raise loop.RunError(f"the run folder {run_dir} is not empty")
    settings = {key: getattr(args, key) for key in loop.DEFAULTS}
    made = run_dir is None
    run_dir = run_dir or runs.new_run(runs.skill_name(folder))
    try:
        job = loop.Run(folder, run_dir, settings, support=_support(args.support))
    except loop.RunError:
        if made:
            shutil.rmtree(run_dir, ignore_errors=True)  # refused before any call: leave no empty run behind
        raise
    report = job.run()
    return 0, report, summary(report)


def _named(skill):
    if skill and (Path(skill).expanduser() / "SKILL.md").is_file():
        return runs.skill_name(Path(skill).expanduser())
    return skill


def _found(args):
    run_dir = runs.find(_named(args.skill), args.run)
    if run_dir is None:
        what = f"run {args.run}" if args.run else "run"
        raise loop.RunError(f"no {what} of {args.skill or 'any skill'} under {runs.home()}")
    return run_dir


def cmd_status(args):
    report = runs.read_json(_found(args) / runs.REPORT)
    return 0, report, summary(report)


def cmd_diff(args):
    run_dir = _found(args)
    diff = (run_dir / runs.DIFF).read_text(encoding="utf-8") if (run_dir / runs.DIFF).is_file() else ""
    return 0, {"run_dir": str(run_dir), "diff": diff, "empty": not diff}, diff.rstrip("\n")


COMMANDS = {"init": cmd_init, "estimate": cmd_estimate, "run": cmd_run, "status": cmd_status, "diff": cmd_diff}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("h", "help", "-h", "--help"):
        print(USAGE)
        return 0
    args = parser().parse_args(argv)
    try:
        code, data, text = COMMANDS[args.command](args)
    except (loop.RunError, evalset.EvalSetError) as exc:
        code, data, text = 1, {"error": str(exc)}, f"optimize-skill: {exc}"
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif text:
        print(text, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
