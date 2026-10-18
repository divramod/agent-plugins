"""`plan.py trailers <n>`: a step commit's origin trailers (hal2 plan 0355, D2)."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "plan.py"

PLAN = """# Plan 0355: commit standards

| # | Step | Status |
|---|---|---|
| 1 | landing subject | done |
| 2 | commit-msg hook | next |
| 3 | skills | |
"""


class TrailersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "05"  # a worktree is named by its number
        (self.root / "plans" / "0355-commit-standards").mkdir(parents=True)
        (self.root / "plans" / "0355-commit-standards" / "plan.md").write_text(PLAN)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        (self.root / "plans" / "CURRENT_PLAN").write_text("0355-commit-standards\n")

    def tearDown(self):
        self.tmp.cleanup()

    def trailers(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "trailers", *args],
                              capture_output=True, text=True, cwd=self.root)

    def test_the_three_lines_of_a_step(self):
        result = self.trailers("3")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["Worktree: 05", "Plan: 0355-commit-standards", "Step: 3/3"])

    def test_the_total_is_the_number_of_all_steps(self):
        self.assertEqual(self.trailers("1", "--plan", "0355").stdout.splitlines()[2], "Step: 1/3")

    def test_a_step_that_is_no_row_is_refused(self):
        result = self.trailers("9")

        self.assertEqual(result.returncode, 1)
        self.assertIn("is no row of plan 0355-commit-standards", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
