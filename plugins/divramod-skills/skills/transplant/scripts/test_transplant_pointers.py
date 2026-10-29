"""The target's plan pointer in the git dir (hal2 plan 0409 step 12): plan_run reads it as it reads plans/CURRENT_PLAN."""

import subprocess
import tempfile
import unittest
from pathlib import Path

import transplant


class GitDirPointer(unittest.TestCase):
    def test_the_targets_run_line_is_found_through_the_git_dir_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=target, check=True)
            (target / ".git/hal").mkdir()
            (target / ".git/hal/CURRENT_PLAN").write_text("0409-plan-store\n")
            self.assertEqual(transplant.plan_run(target), (None, None))  # no plan folder yet
            (target / "plans/0409-plan-store").mkdir(parents=True)
            (target / "plans/0409-plan-store/plan.md").write_text("# x\n\nrun: sonnet high 1m\n")
            self.assertEqual(transplant.plan_run(target), ("sonnet[1m]", "high"))


if __name__ == "__main__":
    unittest.main()
