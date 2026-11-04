"""hal2's dependency scan, `hal2-cli-plans depends check --json`, called by `plan.py check` (hal2 plan 0595 step 8).

The skills call hal2, hal2 calls no skill: the scan (another plan's number in one sentence with wait, needs, after,
requires, blocked or depends, in a plan's step files, decisions.md, handoff.md and questions.md, that its
`depends_on` does not name; D16) lives once, in hal2's Rust lib. Every finding is a problem ending in
`(plan-dependencies)`. Without the binary, or with one that has no `depends check` (older than plan 0595), the scan
is skipped without a word and never fails the check: the questions check already names a missing binary, and an
older one is replaced at the next install; `skipped()` says why for a caller that wants it. The binary is qcheck's:
`$HAL2_CLI_PLANS`, else `hal2-cli-plans` on PATH.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import folder
import qcheck

RULE = "plan-dependencies"
TOO_OLD = f"dependencies unchecked: {qcheck.NAME} has no `depends check` (an older binary)"


def scanned(root: Path, plan_files: list[Path]) -> list[str]:
    """The slugs of `plan_files` (plan.md paths) the scan covers: record plans of the checkout `root`'s plans folder
    that are not done (a legacy plan, a done one and a folder outside `root` pass)."""
    plans = (root / "plans").resolve()
    out = []
    for path in plan_files:
        if path.name != "plan.md" or path.resolve().parent.parent != plans:
            continue
        text = path.read_text()
        if folder.is_record(text) and folder.header(text, "status") != "done":
            out.append(path.parent.name)
    return out


def skipped(root: Path) -> str | None:
    """Why the scan is skipped in `root`: qcheck's NOT_INSTALLED, TOO_OLD, or None when the CLI has the command."""
    cli = qcheck.binary()
    if cli is None:
        return qcheck.NOT_INSTALLED
    out = subprocess.run([str(Path(cli).expanduser()), "help", "depends", "check", "--json"], capture_output=True,
                         text=True, cwd=root)
    try:
        return None if json.loads(out.stdout).get("path") == ["depends", "check"] else TOO_OLD
    except (json.JSONDecodeError, AttributeError):
        return TOO_OLD


def check(root: Path, plan_files: list[Path]) -> list[str]:
    """The undeclared waits of the plans `plan_files` covers ([`scanned`]), one line each: `plans/<slug>/<file>:<line>:
    waits for <NNNN>, not in depends_on: <sentence> (plan-dependencies)`. One CLI run for all."""
    cli = qcheck.binary()
    slugs = scanned(root, plan_files)
    if cli is None or not slugs:
        return []
    args = [str(Path(cli).expanduser()), "depends", "check", "--json", "--repo", str(root)]
    for slug in slugs:
        args += ["--plan", slug]
    out = subprocess.run(args, capture_output=True, text=True, cwd=root)
    try:
        found = json.loads(out.stdout)["plans"] if out.returncode in (0, 1) else None
    except (json.JSONDecodeError, KeyError, TypeError):
        found = None
    if found is None:
        return []
    problems = []
    for plan in found:
        for f in plan.get("findings", []):
            problems.append(f"plans/{plan.get('slug')}/{f['file']}:{f['line']}: waits for {f['plan']:04d}, not in "
                            f"depends_on: {f['text']} ({RULE})")
    return problems
