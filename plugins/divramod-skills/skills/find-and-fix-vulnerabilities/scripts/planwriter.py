"""Write one fix plan from an enriched report: plan.py new, then a step per fix (KEV first). Read-only until it runs.

planwriter.py --input enriched.json [--repo <path>] [--dry-run]"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixsteps import Fix, build_fixes, done_when, items_of, kev_word  # noqa: E402

HERE = Path(__file__).resolve().parent
UAT_ROW = "Write the UATs"
FALLBACK = """---
type: Plan
schema: 1
id: NNNN
title: "{title}"
status: open
---

# Plan NNNN: {title}

## Goal

{goal}

## Brief

- In: <what this plan delivers>
- Out: <what it leaves alone>
- Must: <each requirement one line>
- Proof: <the command or the checks>

## Steps

| # | Step | Done when | Model | Effort | Window | Size | Status |
|---|---|---|---|---|---|---|---|
| 1 | <step> | <check> | opus | medium | 1m | 150k | next |
"""


def plan_script() -> Path | None:
    """The plan skill's plan.py: the repo's, relative to this skill, else the installed one."""
    for p in (HERE.parents[1] / "plan" / "scripts" / "plan.py", Path.home() / ".claude/skills/plan/scripts/plan.py"):
        if p.is_file():
            return p
    return None


class PlanRunner:
    """Runs `plan.py new` in the repo; returns its JSON (with `path`, relative to the repo)."""

    def new(self, repo: Path, name: str, goal: str) -> dict:
        script = plan_script()
        if script is None:
            raise RuntimeError("plan.py not found (the plan skill)")
        cmd = [sys.executable, str(script), "new", "--no-current", "--goal", goal, name]
        done = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=120)
        if done.returncode:
            raise RuntimeError(f"plan.py new failed: {(done.stderr or done.stdout).strip()}")
        return json.loads(done.stdout)


def plan_name(today: dt.date) -> str:
    return f"fix-vulns-{today:%Y%m%d}"  # a date of ten digits counts as three words; this is three in all


def step_row(n: int, fix: Fix) -> str:
    return f"| {n} | {fix.title} | {done_when(fix)} | sonnet | medium | 1m | 100k | {'next' if n == 1 else ''} |"


def brief_lines(fixes: list, total: int) -> dict:
    kev = sum(1 for f in fixes if f.kev)
    targets = sorted({f.target or f.kind for f in fixes})
    return {
        "In": f"- In: fix {total} findings in {len(fixes)} steps ({kev} with KEV), KEV first, on {', '.join(targets)[:120]}.",
        "Out": "- Out: anything else; no other package, host or image is touched.",
        "Must": "- Must: read-only until it runs; each step changes only its own target and package, then rescans.",
        "Proof": "- Proof: a rescan (`collect.py` + `report.py`) shows 0 of these ids.",
    }


def rewrite(text: str, fixes: list, total: int) -> str:
    """The template's plan.md with the placeholder step row replaced by the fix rows and the Brief filled."""
    for key, line in brief_lines(fixes, total).items():
        text = re.sub(rf"^- {key}: <.*>$", lambda m, l=line: l, text, flags=re.M)
    out, last = [], None
    lines = text.split("\n")
    for line in lines:
        if line.startswith("| 1 | <step>"):
            out += [step_row(i, f) for i, f in enumerate(fixes, 1)]
            last = len(fixes)
        elif last is not None and re.match(r"\| \d+ \| " + UAT_ROW, line):
            out.append(re.sub(r"^\| \d+ ", f"| {last + 1} ", line))
        else:
            out.append(line)
    return "\n".join(out)


def step_file(n: int, fix: Fix) -> str:
    rows = [f"- {i.f.id}: {i.f.package} {i.f.version} -> {i.f.fixed_version or 'no fix'}, {i.f.severity}"
            f"{', KEV' + (' (added ' + i.kev_added + ')' if i.kev_added else '') if i.kev else ''}"
            f"{' - ' + i.f.summary[:100] if i.f.summary else ''}" for i in fix.items]
    how = {"os": "Install the pending security updates of the machine, restart where needed.",
           "bump": "Bump the package to the fixed version in the manifest and lockfile, build and test.",
           "mitigate": "No fixed version is known: mitigate (config, firewall, disable) or remove the package.",
           "rebuild": "Rebuild the image or VM on a newer base image (these OS packages have no fixed version), then rescan.",
           "group": "Fix each package below as in its row; bump where a fixed version exists, else mitigate or remove."}
    return (f"# Step {n}: {fix.title}\n\n## Task\n\n{how[fix.mode]} Target: {fix.target or fix.kind} "
            f"(KEV: {kev_word(fix)}, {fix.severity}).\n\nDone when: {done_when(fix)}\n\n## Notes\n\n"
            + "\n".join(rows) + "\n")


def skeleton(goal: str, title: str) -> str:
    """What plan.py new would write, for a dry run: the plan skill's template, else a short one."""
    tpl = HERE.parents[1] / "plan" / "templates" / "plan.md"
    if tpl.is_file():
        class D(dict):
            def __missing__(self, k):
                return "NNNN"
        return tpl.read_text().format_map(D(goal=goal, title=title, quoted_title=f'"{title}"', description=goal,
                                            landing="auto", date=dt.date.today().isoformat()))
    return FALLBACK.format(goal=goal, title=title)


def write_plan(report: dict, repo: Path, dry_run: bool = False, runner=None, today=None) -> str:
    items = items_of(report)
    if not items:
        return "no findings: no plan written"
    fixes = build_fixes(items)
    name = plan_name(today or dt.date.today())
    goal = f"{len(items)} vulnerabilities: fix KEV first"
    if dry_run:
        return rewrite(skeleton(goal, name), fixes, len(items))
    info = (runner or PlanRunner()).new(repo, name, goal)
    path = repo / info["path"]
    path.write_text(rewrite(path.read_text(), fixes, len(items)))
    steps = path.parent / "steps"
    steps.mkdir(exist_ok=True)
    for n, fix in enumerate(fixes, 1):
        (steps / f"{n}.md").write_text(step_file(n, fix))
    return str(path.relative_to(repo))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Write one fix plan from an enriched findings report.")
    ap.add_argument("--input", required=True, help="the enriched report JSON ('-' for stdin)")
    ap.add_argument("--repo", default=os.getcwd(), help="the repository to write the plan into (default: cwd)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan.md it would write, change nothing")
    a = ap.parse_args(argv)
    try:
        text = sys.stdin.read() if a.input == "-" else Path(a.input).read_text()
        print(write_plan(json.loads(text), Path(a.repo), a.dry_run))
    except (OSError, ValueError, RuntimeError) as e:
        print(f"planwriter.py: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
