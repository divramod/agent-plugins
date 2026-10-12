"""plan_number.py: numbers stay unique across worktrees, branches, remotes and concurrent calls."""
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "plan_number.py"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, text=True, capture_output=True, check=True).stdout


class PlanNumberTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.main = base / "main"
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        self.add_plan(self.main, "0001-first.md", commit=True)
        self.base = base

    def tearDown(self):
        self.tmp.cleanup()

    def add_plan(self, tree, name, commit=False):
        plans = tree / "plans"
        plans.mkdir(parents=True, exist_ok=True)
        (plans / name).write_text(f"# {name}\n")
        if commit:
            git(tree, "add", ".")
            git(tree, "commit", "-qm", f"plan {name}")

    def run_number(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd or self.main, env=ENV,
                              text=True, capture_output=True)

    def next(self, *args, cwd=None):
        result = self.run_number("next", *args, cwd=cwd)
        self.assertEqual(result.returncode, 0, result.stderr)
        return int(result.stdout)

    def test_sees_uncommitted_plan_in_another_worktree(self):
        tree = self.base / "wt-user"
        git(self.main, "worktree", "add", "-q", "-b", "user", str(tree))
        self.add_plan(tree, "0002-in-user-worktree.md")  # not committed anywhere
        self.assertEqual(self.next("--no-reserve"), 3)
        self.assertEqual(self.next("--no-reserve", cwd=tree), 3)

    def test_sees_plans_on_other_branches_and_remotes(self):
        git(self.main, "switch", "-q", "-c", "feature")
        self.add_plan(self.main, "0004-on-feature.md", commit=True)
        git(self.main, "switch", "-q", "main")
        self.assertFalse((self.main / "plans/0004-on-feature.md").exists())
        self.assertEqual(self.next("--no-reserve"), 5)

        git(self.main, "switch", "-q", "-c", "elsewhere")
        self.add_plan(self.main, "0007-other-machine.md", commit=True)
        sha = git(self.main, "rev-parse", "HEAD").strip()
        git(self.main, "switch", "-q", "main")
        git(self.main, "branch", "-q", "-D", "elsewhere")
        git(self.main, "update-ref", "refs/remotes/origin/elsewhere", sha)  # only a remote-tracking ref has it
        self.assertEqual(self.next("--no-reserve"), 8)

    def test_legacy_docs_plans_on_an_old_branch_still_counts(self):
        git(self.main, "switch", "-q", "-c", "old-layout")
        legacy = self.main / "docs/plans"
        legacy.mkdir(parents=True)
        (legacy / "0006-before-the-move.md").write_text("# old\n")
        git(self.main, "add", ".")
        git(self.main, "commit", "-qm", "old plan")
        git(self.main, "switch", "-q", "main")
        self.assertEqual(self.next("--no-reserve"), 7)

    def test_reservations_are_shared_and_idempotent_per_slug(self):
        tree = self.base / "wt-1"
        git(self.main, "worktree", "add", "-q", "-b", "wt1", str(tree))
        first = self.next("--slug", "alpha")
        second = self.next("--slug", "beta", cwd=tree)  # other worktree, nothing committed yet
        self.assertEqual((first, second), (2, 3))
        self.assertEqual(self.next("--slug", "alpha", cwd=tree), 2)

    def test_concurrent_calls_get_distinct_numbers(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            numbers = list(pool.map(lambda i: self.next("--slug", f"plan-{i}"), range(8)))
        self.assertEqual(sorted(numbers), list(range(2, 10)))

    def test_check_reports_a_number_used_twice(self):
        self.assertEqual(self.run_number("check").returncode, 0)
        git(self.main, "switch", "-q", "-c", "a")
        self.add_plan(self.main, "0002-from-a.md", commit=True)
        git(self.main, "switch", "-q", "main")
        self.add_plan(self.main, "0002-from-main.md", commit=True)
        result = self.run_number("check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("0002-from-a", result.stdout)
        self.assertIn("0002-from-main", result.stdout)

    def test_reservation_for_an_existing_plan_is_not_a_duplicate(self):
        number = self.next("--slug", "real")
        self.add_plan(self.main, f"{number:04d}-real.md")
        self.assertEqual(self.run_number("check").returncode, 0)


if __name__ == "__main__":
    unittest.main()
