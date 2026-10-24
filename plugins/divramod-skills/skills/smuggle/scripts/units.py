#!/usr/bin/env python3
"""The units a smuggle may land: `.hal/smuggle.toml` (hal2 plan 0360 D49, D63), read from the commit --rev (HEAD),
so a branch that widens the list finds its own change outside it.

  units.py touched [--base <rev>] [--rev <rev>] [--repo <dir>]   JSON: the touched units (`files` each) and `outside`
  units.py warn [--base <rev>] [--yes-outside] [--repo <dir>]    the preflight's warning; exit 4 for a path outside
  units.py run checks|build|install [--base <rev>] [--rev <rev>] [--report <file>] [--dry-run] [--repo <dir>]

The list: `free` (paths never warned about and no unit's: plans, generated files) and one `[[unit]]` each with
`name`, `paths`, `checks`, `build`, `install` (shell commands, run by bash in the repository's top with SMUGGLE_BASE,
SMUGGLE_YARD (the main checkout) and SMUGGLE_FILES (the unit's changed paths, one a line)). A path matches a pattern
that is the path itself, a folder above it or an fnmatch glob. The changes: <base>'s merge base .. --rev, and with
--rev HEAD the working tree's changes and untracked files too. --base defaults to origin/<default branch>.
`run checks` in a repository with `.github/hal2-changes.toml` runs the job map's selection (jobmap.py: one
`hal2-cli-git changes --keys --json`, the selected gate jobs with their packages, a job green before skipped, a green
one on a clean tree marked) instead of the units' `checks`, but only when every run job is a gate job; a run job the
gate does not know (`unmapped`) or no runnable job runs the units' `checks` too (plan 0427); they are also the fallback
without a map. `run` runs the touched units one after the other, a unit stopping at its first red command; `--report` gets a JSON
line per unit (`lane`, `status`, `seconds`, `jobs`), the form hal2-git's smuggle reads (SMUGGLE_REPORT). With
SMUGGLE_RUN_LOGS set each command is a step of the smuggle's run, timed and measured (runsteps.py).
Exit: 0 ok, 1 red or an error, 4 a path outside the units (warn), 64 usage.
"""

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobmap  # noqa: E402
import runsteps  # noqa: E402

LIST = ".hal/smuggle.toml"
KEYS = ("checks", "build", "install")


def git(repo, *args, check=True):
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=False)
    if check and out.returncode != 0:
        sys.exit(f"units.py: git {' '.join(args)}: {out.stderr.strip()}")
    return out


def default_base(repo):
    ref = git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False).stdout.strip()
    return ref or "origin/main"


def load_list(repo, rev):
    """The list at <rev>, or None when that commit has none."""
    shown = git(repo, "show", f"{rev}:{LIST}", check=False)
    if shown.returncode != 0:
        return None
    try:
        import tomllib
    except ImportError:  # python3 before 3.11
        sys.exit("units.py: needs python3 3.11 or newer (tomllib)")
    return tomllib.loads(shown.stdout)


def changed(repo, base, rev):
    """The paths the change touches, sorted."""
    fork = git(repo, "merge-base", base, rev).stdout.strip()
    paths = set(git(repo, "diff", "--name-only", fork, rev).stdout.split("\n"))
    if rev == "HEAD":
        paths |= set(git(repo, "diff", "--name-only", "HEAD").stdout.split("\n"))
        paths |= set(git(repo, "ls-files", "--others", "--exclude-standard").stdout.split("\n"))
    return sorted(path for path in paths if path)


def matches(path, patterns):
    return any(path == p or path.startswith(p.rstrip("/") + "/") or fnmatch.fnmatchcase(path, p) for p in patterns)


def touched(repo, base, rev):
    """{"list": <path or None>, "units": [unit + files], "outside": [paths]}."""
    spec = load_list(repo, rev)
    paths = changed(repo, base, rev)
    if spec is None:
        return {"list": None, "units": [], "outside": paths}
    units = []
    for unit in spec.get("unit", []):
        files = [p for p in paths if matches(p, unit.get("paths", []))]
        if files:
            units.append({"name": unit["name"], "files": files, **{k: unit.get(k, []) for k in KEYS}})
    inside = {f for unit in units for f in unit["files"]}
    free = spec.get("free", [])
    outside = [p for p in paths if p not in inside and not matches(p, free)]
    return {"list": LIST, "units": units, "outside": outside}


def ci_jobs(repo, base):
    """The gate jobs `hal2-cli-git changes` runs for the change, or None when it cannot say."""
    try:
        cli = os.environ.get("HAL2_CLI_GIT", "hal2-cli-git")
        out = subprocess.run([cli, "changes", "--branch", base, "--json", "--repo", repo],
                             capture_output=True, text=True, check=False)
        jobs = json.loads(out.stdout)["jobs"]
    except (OSError, ValueError, KeyError):
        return None
    return [job["name"] for job in jobs if job.get("run")]


def warn(repo, base, yes):
    state = touched(repo, base, "HEAD")
    if state["list"] is None:
        print(f"units: no {LIST} at HEAD: no unit list, no warning")
        return 0
    print("units: " + (", ".join(u["name"] for u in state["units"]) or "none"))
    if not state["outside"]:
        return 0
    head = "outside the units, the user said yes:" if yes else f"outside every unit of {LIST}:"
    print(head)
    for path in state["outside"]:
        print(f"  {path}")
    jobs = ci_jobs(repo, base)
    print("CI would have run: " + (", ".join(jobs) or "nothing" if jobs is not None else "unknown (no hal2-cli-git)"))
    if yes:
        return 0
    print("ask the user once (Q form); only on the user's yes rerun with --yes-outside")
    return 4


def run_unit(repo, unit, key, env, dry):
    """Runs <unit>'s <key> commands; its report line."""
    start, status = time.monotonic(), "ok"
    lane = runsteps.Lane(unit["name"], {} if dry else env)
    for command in unit[key]:
        if dry:
            print(f"would run: {unit['name']}: {command}")
            continue
        print(f"== {unit['name']}: {command}", flush=True)
        step = runsteps.step_name(command)
        if lane.run(step, ["bash", "-c", command], repo, env, rust="cargo" in command) != 0:
            print(f"== {unit['name']}: red", flush=True)
            status = "red"
            break
    return {"lane": unit["name"], "status": status, "seconds": round(time.monotonic() - start), "jobs": unit[key]}


def run_job_map(repo, sel, base, rev, report, dry, env):
    """`run checks` with a job map: the selected gate jobs; the exit code."""
    line = jobmap.run_selection(repo, sel, base, rev, env, dry)
    if report and not dry:
        with open(report, "a", encoding="utf-8") as out:
            out.write(json.dumps(line) + "\n")
    return 1 if line["status"] == "red" else 0


def run(repo, key, base, rev, report, dry):
    state = touched(repo, base, rev)
    map_red = 0
    if key == "checks" and any(unit["checks"] for unit in state["units"]):
        sel = jobmap.select(repo, base, rev)
        if sel is not None:
            if sel["jobs"]:
                map_red = run_job_map(repo, sel, base, rev, report, dry, dict(os.environ, SMUGGLE_BASE=base))
            # The map replaces the units' commands only when every run job is a gate job (plan 0420 D4); jobs the
            # gate cannot run, or none runnable, leave the units' own checks to run (plan 0427).
            if sel["jobs"] and not sel["unmapped"]:
                return map_red
            if sel["unmapped"]:
                print("units: job map jobs the gate does not know: " + ", ".join(sel["unmapped"])
                      + ": running the units' checks too", flush=True)
    yard = git(repo, "worktree", "list", "--porcelain").stdout.split("\n")[0].removeprefix("worktree ")
    red = map_red
    for unit in state["units"]:
        if not unit[key]:
            continue
        env = dict(os.environ, SMUGGLE_BASE=base, SMUGGLE_YARD=yard, SMUGGLE_FILES="\n".join(unit["files"]))
        line = run_unit(repo, unit, key, env, dry)
        red |= line["status"] == "red"
        if report and not dry:
            with open(report, "a", encoding="utf-8") as out:
                out.write(json.dumps(line) + "\n")
    return 1 if red else 0


def parse(argv):
    parser = argparse.ArgumentParser(prog="units.py", add_help=True)
    parser.add_argument("command", choices=("touched", "warn", "run"))
    parser.add_argument("key", nargs="?")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base")
    parser.add_argument("--rev", default="HEAD")
    parser.add_argument("--report")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes-outside", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        sys.exit(64)
    if (args.command == "run") != (args.key in KEYS):
        print(f"units.py: `run` takes one of {', '.join(KEYS)}, the others none", file=sys.stderr)
        sys.exit(64)
    return args


def main(argv):
    args = parse(argv)
    repo = git(args.repo, "rev-parse", "--show-toplevel").stdout.strip()
    base = args.base or default_base(repo)
    if args.command == "touched":
        print(json.dumps(touched(repo, base, args.rev), indent=2))
        return 0
    if args.command == "warn":
        return warn(repo, base, args.yes_outside)
    return run(repo, args.key, base, args.rev, args.report, args.dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
