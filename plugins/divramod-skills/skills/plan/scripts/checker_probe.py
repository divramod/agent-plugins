"""Shared by the tests of the plugins that make a plan with `plan.py new` and expect hal2's records checker to pass it.

A checker older than hal2 plan 0293 step 2 (the installed build, until hal2 is reinstalled) refuses the `## Brief`
every new plan holds (`section ## Brief ... (spec:section-unknown)`). `needs_brief_checker` skips a test then, like
one without any checker (for a test that needs the checker); `unless_brief_refused` skips only when a checker is there
and refuses (for a test that also passes without one, where the check is advisory). `$HAL2_CLI_RECORDS` names a newer
build (the branch's own `target/debug/hal2-cli-records`).
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import checker

SCRIPT = Path(__file__).resolve().parent / "plan.py"
SKIP = f"{checker.NAME} is missing or older than the Brief (plan 0293)"


def accepts_brief() -> bool:
    """Does the records checker accept the `## Brief` a new plan holds? Probed once, on a plan made in a temp repo."""
    if not checker.binary():
        return False
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True, capture_output=True)
        subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), "new", "Probe"], capture_output=True)
        result = checker.check(repo=root)
    return result is not None and not any("Brief" in p["message"] for p in result["problems"])


ACCEPTS = accepts_brief()
needs_brief_checker = unittest.skipUnless(ACCEPTS, SKIP)
unless_brief_refused = unittest.skipIf(bool(checker.binary()) and not ACCEPTS, SKIP)
