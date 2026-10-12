"""since.sh reports commits and changes made after a handoff was written."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "since.sh"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, env=ENV, text=True, capture_output=True, check=True).stdout


class SinceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("1\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "init")
        self.sha = git(self.repo, "rev-parse", "--short", "HEAD").strip()
        self.handoff = self.repo / "HANDOFF.md"

    def tearDown(self):
        self.tmp.cleanup()

    def since(self):
        return subprocess.run(["bash", str(SCRIPT)], cwd=self.repo, env=ENV, text=True, capture_output=True)

    def write_handoff(self, sha):
        self.handoff.write_text(f"# Handoff\n\nUpdated 2026-09-26, branch `main`, written at `{sha}`.\n")
        (self.repo / "INTENT.md").write_text("# Intent\n")  # committed together with the handoff
        git(self.repo, "add", "HANDOFF.md", "INTENT.md")
        git(self.repo, "commit", "-qm", "docs: update handoff")

    def test_nothing_since(self):
        self.write_handoff(self.sha)
        out = self.since()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("commits since: none", out.stdout)  # the handoff commit itself is ignored
        self.assertIn("uncommitted: none", out.stdout)

    def test_reports_commits_and_changes(self):
        self.write_handoff(self.sha)
        (self.repo / "a.txt").write_text("2\n")
        git(self.repo, "commit", "-qam", "feat: parallel session work")
        (self.repo / "b.txt").write_text("new\n")
        out = self.since().stdout
        self.assertIn("feat: parallel session work", out)
        self.assertIn("?? b.txt", out)

    def test_missing_stamp_or_file(self):
        self.assertEqual(self.since().returncode, 1)
        self.handoff.write_text("# Handoff\n")
        self.assertEqual(self.since().returncode, 1)


if __name__ == "__main__":
    unittest.main()
