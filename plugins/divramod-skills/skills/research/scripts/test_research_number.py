"""research_number.py: research numbers stay unique across worktrees, branches and concurrent calls, and the
plan skill's numbering it reuses keeps plans and research apart."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "research_number.py"
PLAN_SCRIPT = HERE.parents[1] / "plan" / "scripts" / "plan_number.py"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, text=True, capture_output=True, check=True).stdout


class ResearchNumberTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.main = self.base / "main"
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        self.add(self.main, "research/0001-first", commit=True)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, tree, rel, commit=False):
        folder = tree / rel
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "research.md").write_text("# x\n")
        if commit:
            git(tree, "add", ".")
            git(tree, "commit", "-qm", rel)

    def run_script(self, *args, cwd=None, script=SCRIPT):
        return subprocess.run([sys.executable, str(script), *args], cwd=cwd or self.main, env=ENV, text=True,
                              capture_output=True)

    def next(self, *args, cwd=None):
        result = self.run_script("next", *args, cwd=cwd)
        self.assertEqual(result.returncode, 0, result.stderr)
        return int(result.stdout)

    def test_sees_other_worktrees_branches_and_remotes(self):
        tree = self.base / "wt"
        git(self.main, "worktree", "add", "-q", "-b", "wt", str(tree))
        self.add(tree, "research/0002-uncommitted")
        self.assertEqual(self.next("--no-reserve"), 3)
        git(self.main, "switch", "-q", "-c", "gone")
        self.add(self.main, "research/0005-remote-only", commit=True)
        sha = git(self.main, "rev-parse", "HEAD").strip()
        git(self.main, "switch", "-q", "main")
        git(self.main, "branch", "-q", "-D", "gone")
        git(self.main, "update-ref", "refs/remotes/origin/gone", sha)
        self.assertEqual(self.next("--no-reserve", cwd=tree), 6)

    def test_plans_and_research_are_numbered_apart(self):
        self.add(self.main, "plans/0009-a-plan")
        self.assertEqual(self.next("--no-reserve"), 2)
        plan = self.run_script("next", "--no-reserve", script=PLAN_SCRIPT)
        self.assertEqual(int(plan.stdout), 10)

    def test_reservations_are_shared_idempotent_and_in_their_own_file(self):
        tree = self.base / "wt"
        git(self.main, "worktree", "add", "-q", "-b", "wt", str(tree))
        self.assertEqual((self.next("--slug", "alpha"), self.next("--slug", "beta", cwd=tree)), (2, 3))
        self.assertEqual(self.next("--slug", "alpha", cwd=tree), 2)
        common = Path(git(self.main, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
        self.assertIn("0003-beta", json.loads((common / "research-numbers.json").read_text()))
        self.assertFalse((common / "plan-numbers.json").exists())

    def test_concurrent_calls_get_distinct_numbers(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            numbers = list(pool.map(lambda i: self.next("--slug", f"r-{i}"), range(6)))
        self.assertEqual(sorted(numbers), list(range(2, 8)))

    def test_check_reports_a_number_used_twice(self):
        ok = self.run_script("check")
        self.assertEqual(ok.returncode, 0)
        self.assertIn("no research number", ok.stdout)
        git(self.main, "switch", "-q", "-c", "a")
        self.add(self.main, "research/0002-from-a", commit=True)
        git(self.main, "switch", "-q", "main")
        self.add(self.main, "research/0002-from-main", commit=True)
        result = self.run_script("check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("0002-from-a", result.stdout)


if __name__ == "__main__":
    unittest.main()
