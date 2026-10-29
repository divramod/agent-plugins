"""commit-handoff.sh commits exactly the named docs and leaves other changes untouched."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import handoff_testkit as kit

SCRIPT = Path(__file__).resolve().parent / "commit-handoff.sh"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}


def run(repo, *args, check=True):
    return subprocess.run(args, cwd=repo, env=ENV, text=True, capture_output=True, check=check)


class CommitHandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        kit.seed(self.repo, {"code.txt": "v1\n"})

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, *args):
        return run(self.repo, "bash", str(SCRIPT), *args, check=False)

    def committed(self):
        lines = run(self.repo, "git", "show", "--name-status", "--format=%s", "HEAD").stdout.split("\n")
        return lines[0], sorted(filter(None, lines[1:]))

    def message(self):
        return run(self.repo, "git", "log", "-1", "--format=%B").stdout.rstrip("\n")

    def test_the_origin_goes_into_trailers_before_the_attribution(self):
        (self.repo / "plans").mkdir()
        (self.repo / "plans" / "CURRENT_PLAN").write_text("0355-commit-standards\n")
        (self.repo / "INTENT.md").write_text("# Intent\n")
        attribution = "Co-Authored-By: C <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_1"

        result = self.commit(f"docs(plans): record the decisions of plan 0355\n\n{attribution}", "INTENT.md")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.message(), "docs(plans): record the decisions of plan 0355\n\n"
                         f"Worktree: {self.repo.name}\nPlan: 0355-commit-standards\n{attribution}")

    def test_the_plan_trailer_reads_a_pointer_that_sits_in_the_git_dir(self):
        (self.repo / ".git" / "hal").mkdir()
        (self.repo / ".git" / "hal" / "CURRENT_PLAN").write_text("0355-commit-standards\n")
        (self.repo / "INTENT.md").write_text("# Intent\n")

        self.assertEqual(self.commit("docs: note", "INTENT.md").returncode, 0)

        self.assertEqual(self.message(), f"docs: note\n\nWorktree: {self.repo.name}\nPlan: 0355-commit-standards")

    def test_without_a_plan_only_the_worktree_trailer_and_a_given_one_is_kept(self):
        (self.repo / "INTENT.md").write_text("# Intent\n")
        self.assertEqual(self.commit("docs: note\n\nWorktree: 07", "INTENT.md").returncode, 0)
        self.assertEqual(self.message(), "docs: note\n\nWorktree: 07")
        (self.repo / "INTENT.md").write_text("# Intent 2\n")
        self.assertEqual(self.commit("docs: note again", "INTENT.md").returncode, 0)
        self.assertEqual(self.message(), f"docs: note again\n\nWorktree: {self.repo.name}")

    def test_commits_only_the_docs_and_ignores_the_handoff(self):
        (self.repo / "code.txt").write_text("staged\n")
        run(self.repo, "git", "add", "code.txt")
        (self.repo / "other.txt").write_text("untracked\n")
        (self.repo / "HANDOFF.md").write_text("# Handoff\n")
        (self.repo / "INTENT.md").write_text("# Intent\n")

        result = self.commit("docs: update handoff", "HANDOFF.md", "INTENT.md")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.committed(), ("docs: update handoff", ["A\t.gitignore", "A\tINTENT.md"]))
        self.assertIn("HANDOFF.md", (self.repo / ".gitignore").read_text())
        status = run(self.repo, "git", "status", "--short").stdout
        self.assertIn("M  code.txt", status)  # still staged, not committed
        self.assertIn("?? other.txt", status)
        self.assertNotIn("HANDOFF.md", status)

    def test_a_tracked_handoff_is_untracked_and_kept_on_disk(self):
        (self.repo / ".gitignore").write_text("build/")  # no newline at the end
        (self.repo / "HANDOFF.md").write_text("# old\n")
        run(self.repo, "git", "add", ".")
        run(self.repo, "git", "commit", "-qm", "tracked handoff")
        (self.repo / "HANDOFF.md").write_text("# new\n")

        result = self.commit("docs: update handoff", "HANDOFF.md")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.committed(), ("docs: update handoff", ["D\tHANDOFF.md", "M\t.gitignore"]))
        self.assertEqual((self.repo / ".gitignore").read_text().splitlines()[0], "build/")
        self.assertEqual((self.repo / "HANDOFF.md").read_text(), "# new\n")
        self.assertEqual(run(self.repo, "git", "status", "--short").stdout, "")

    def test_unchanged_docs_are_a_no_op(self):
        (self.repo / "INTENT.md").write_text("x\n")
        self.assertEqual(self.commit("msg", "INTENT.md").returncode, 0)
        head = run(self.repo, "git", "rev-parse", "HEAD").stdout
        result = self.commit("msg", "INTENT.md")
        self.assertEqual(result.returncode, 0)
        self.assertIn("nothing to commit", result.stdout)
        self.assertEqual(run(self.repo, "git", "rev-parse", "HEAD").stdout, head)
        self.assertEqual(self.commit("only-a-message").returncode, 0)
        self.assertEqual(run(self.repo, "git", "rev-parse", "HEAD").stdout, head)

    def test_missing_file_fails(self):
        self.assertEqual(self.commit("msg", "nope.md").returncode, 1)
        self.assertEqual(self.commit().returncode, 1)


if __name__ == "__main__":
    unittest.main()
