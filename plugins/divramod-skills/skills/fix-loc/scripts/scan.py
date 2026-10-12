#!/usr/bin/env python3
"""fix-loc's scanner: which units have files above the size limit, most worth fixing first.

  scan.py scan  --repo R [--ref origin/main] [--skip-branch NN] [--json]  units over the limit, hotspot first
  scan.py unit  --repo R <unit> [--worktree] [--json]                     a unit's files and their code lines
  scan.py check --repo R <unit> [--worktree] [--json]                     exit 0 when every file is within the limit

`scan` and `unit` read the default branch's committed tree (a git archive under the state root), `--worktree`
the working tree of `--repo`. Exit 2: a missing tool (run install-prerequisites.sh).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import count  # noqa: E402
import layout  # noqa: E402


def state_root(repo):
    """`~/skills/fix-loc/<repo>/` (FIX_LOC_ROOT overrides `~/skills/fix-loc`)."""
    base = Path(os.environ.get("FIX_LOC_ROOT", Path.home() / "skills" / "fix-loc"))
    return base / Path(layout.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent.name


def snapshot(repo, ref):
    """The committed tree of `ref`, extracted to `<state root>/tree`; returns its folder."""
    subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin"], capture_output=True)
    tree = state_root(repo) / "tree"
    shutil.rmtree(tree, ignore_errors=True)
    tree.mkdir(parents=True)
    archive = subprocess.Popen(["git", "-C", str(repo), "archive", ref], stdout=subprocess.PIPE)
    with archive.stdout:
        subprocess.run(["tar", "-x", "-C", str(tree)], stdin=archive.stdout, check=True)
    if archive.wait() != 0:
        raise SystemExit(f"fix-loc: git archive {ref} failed")
    return tree


def measure(root, files, settings):
    """[{path, unit, code}] for the counted files among `files` (tracked paths relative to `root`)."""
    wanted = [f for f in files if not layout.excluded(f, settings.exclude) and layout.unit_of(f, settings.units)]
    counts = count.code_lines(root, wanted)
    return [{"path": p, "unit": layout.unit_of(p, settings.units), "code": counts[p]} for p in wanted if p in counts]


def files_of(root, files):
    """The tracked files of the snapshot folder `root`, or of a working tree."""
    if files is not None:
        return files
    return [str(p.relative_to(root)) for p in Path(root).rglob("*") if p.is_file()]


def over_units(measured, limit, commits, busy):
    """Units with a file above `limit`, each {unit, score, busy, files}, highest score first."""
    units = {}
    for entry in measured:
        if entry["code"] <= limit:
            continue
        entry = {**entry, "over": entry["code"] - limit, "commits": commits.get(entry["path"], 0)}
        units.setdefault(entry["unit"], []).append(entry)
    result = []
    for unit, files in units.items():
        files.sort(key=lambda f: (f["over"] * (1 + f["commits"]), f["code"]), reverse=True)
        result.append({
            "unit": unit,
            "score": sum(f["over"] * (1 + f["commits"]) for f in files),
            "lines_over": sum(f["over"] for f in files),
            "busy": any(path.startswith(unit + "/") for path in busy),
            "files": files,
        })
    result.sort(key=lambda u: (u["busy"], -u["score"], -u["lines_over"]))
    return result


def scan(repo, ref=None, skip_branches=()):
    ref = ref or layout.default_branch(repo)
    tree = snapshot(repo, ref)
    settings = layout.settings(tree)
    measured = measure(tree, files_of(tree, None), settings)
    busy = layout.busy_files(repo, ref, skip_branches)
    return {"ref": ref, "limit": settings.limit, "units": over_units(measured, settings.limit, layout.commits_per_file(repo, ref), busy)}


def unit_files(repo, unit, worktree):
    root = Path(repo) if worktree else snapshot(repo, layout.default_branch(repo))
    settings = layout.settings(root)
    files = layout.tracked(root) if worktree else files_of(root, None)
    measured = [m for m in measure(root, files, settings) if m["unit"] == unit]
    return {"unit": unit, "limit": settings.limit, "files": sorted(measured, key=lambda m: -m["code"])}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="scan.py")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "unit", "check"):
        p = sub.add_parser(name)
        p.add_argument("--repo", default=".")
        p.add_argument("--json", action="store_true")
        if name == "scan":
            p.add_argument("--ref")
            p.add_argument("--skip-branch", action="append", default=[])
        else:
            p.add_argument("unit")
            p.add_argument("--worktree", action="store_true")
    args = parser.parse_args(argv)
    if shutil.which("git") is None:
        print("fix-loc: git is missing -> brew install git", file=sys.stderr)
        return 2
    if args.command == "scan":
        result = scan(args.repo, args.ref, args.skip_branch)
        lines = [f"{u['unit']}  score {u['score']}  {len(u['files'])} files over{'  (busy)' if u['busy'] else ''}" for u in result["units"]]
    else:
        result = unit_files(args.repo, args.unit.rstrip("/"), args.worktree)
        over = [f for f in result["files"] if f["code"] > result["limit"]]
        result["over"] = over
        lines = [f"{f['code']:>6}  {f['path']}{'  OVER' if f['code'] > result['limit'] else ''}" for f in result["files"]]
    print(json.dumps(result, indent=1) if args.json else "\n".join(lines) or "nothing over the limit")
    return 1 if args.command == "check" and result["over"] else 0


if __name__ == "__main__":
    sys.exit(main())
