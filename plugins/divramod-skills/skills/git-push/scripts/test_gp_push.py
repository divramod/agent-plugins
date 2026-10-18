"""Tests of `gp.py ignore`, `push` and the script call, in temporary git repositories (a bare remote for the push)."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gp import Base, git, run_gp, write  # noqa: E402


class IgnoreTests(Base):
    def test_appends_once(self):
        write(self.root, ".gitignore", "target/")  # no trailing newline
        code, out, _ = run_gp("--repo", str(self.root), "ignore", "*.log", "target/", "*.log", ".DS_Store")
        self.assertEqual(code, 0)
        self.assertIn("added 2 of 4", out)
        self.assertEqual(Path(self.root, ".gitignore").read_text(), "target/\n*.log\n.DS_Store\n")
        run_gp("--repo", str(self.root), "ignore", "*.log")
        self.assertEqual(Path(self.root, ".gitignore").read_text().count("*.log"), 1)

    def test_creates_gitignore_and_ignored_files_leave_the_scan(self):
        write(self.root, "a.log")
        self.assertEqual(self.scan()["ignore_candidates"][0]["pattern"], "*.log")
        run_gp("--repo", str(self.root), "ignore", "*.log")
        result = self.scan()
        self.assertEqual(result["ignore_candidates"], [])
        self.assertEqual([g["unit"] for g in result["groups"]], ["root"])

    def test_warns_about_tracked(self):
        code, _, err = run_gp("--repo", str(self.root), "ignore", "README.md")
        self.assertEqual(code, 0)
        self.assertIn("tracked", err)


class PushTests(Base):
    def setUp(self):
        super().setUp()
        self.remote = Path(self.base, "remote.git")
        git(self.base, "init", "-q", "--bare", "-b", "main", str(self.remote))
        git(self.root, "remote", "add", "origin", str(self.remote))

    def test_first_push_sets_upstream(self):
        code, out, _ = run_gp("--repo", str(self.root), "push")
        self.assertEqual(code, 0, out)
        self.assertIn("pushed main", out)
        self.assertIn("main", git(self.remote, "branch"))
        self.assertEqual(git(self.root, "rev-parse", "--abbrev-ref", "@{u}").strip(), "origin/main")
        write(self.root, "a.txt")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "feat: a")
        write(self.root, "b.txt")
        code, out, _ = run_gp("--repo", str(self.root), "push")
        self.assertEqual(code, 0)
        self.assertIn("1 uncommitted files left", out)
        self.assertEqual(git(self.remote, "rev-parse", "main"), git(self.root, "rev-parse", "HEAD"))

    def test_refuses_default_branch_with_a_merge_queue(self):
        write(self.root, ".github/workflows/dev-merge-to-main.yml", "name: x\n")
        code, _, err = run_gp("--repo", str(self.root), "push")
        self.assertEqual(code, 1)
        self.assertIn("/mtm", err)
        self.assertEqual(git(self.remote, "branch").strip(), "")

    def test_pushes_the_head_to_the_branch_of_its_own_name(self):
        run_gp("--repo", str(self.root), "push")
        git(self.root, "checkout", "-q", "-b", "05")
        git(self.root, "push", "-q", "-u", "origin", "05:other")  # upstream is origin/other, push.default would balk
        write(self.root, "a.txt")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "feat: a")
        code, out, err = run_gp("--repo", str(self.root), "push")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(git(self.remote, "rev-parse", "05"), git(self.root, "rev-parse", "HEAD"))

    def test_refuses_a_branch_that_tracks_the_default_branch_of_a_merge_queue_repo(self):
        write(self.root, ".github/workflows/dev-merge-to-main.yml", "name: x\n")
        git(self.root, "push", "-q", "origin", "main")  # the setup push; the script itself would refuse it
        git(self.root, "checkout", "-q", "-b", "05", "--track", "origin/main")
        write(self.root, "a.txt")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "feat: a")
        main_head = git(self.remote, "rev-parse", "main")
        code, _, err = run_gp("--repo", str(self.root), "push")
        self.assertEqual(code, 1)
        self.assertIn("/mtm", err)
        self.assertEqual(git(self.remote, "rev-parse", "main"), main_head)
        self.assertNotIn("05", git(self.remote, "branch"))

    def test_field_branch_may_push_with_a_merge_queue(self):
        write(self.root, ".github/workflows/merge-to-main.yml", "name: x\n")
        git(self.root, "checkout", "-q", "-b", "05")
        code, out, _ = run_gp("--repo", str(self.root), "push")
        self.assertEqual(code, 0, out)
        self.assertIn("05", git(self.remote, "branch"))

    def test_never_forces(self):
        run_gp("--repo", str(self.root), "push")
        other = Path(self.base, "other")
        git(self.base, "clone", "-q", str(self.remote), str(other))
        git(other, "config", "user.name", "T")
        git(other, "config", "user.email", "t@example.com")
        write(other, "o.txt")
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "feat: other")
        git(other, "push", "-q")
        write(self.root, "m.txt")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "feat: mine")
        remote_head = git(self.remote, "rev-parse", "main")
        code, _, err = run_gp("--repo", str(self.root), "push")
        self.assertEqual(code, 1)
        self.assertIn("never force", err)
        self.assertEqual(git(self.remote, "rev-parse", "main"), remote_head)

    def test_detached_head(self):
        git(self.root, "checkout", "-q", "--detach")
        code, _, err = run_gp("--repo", str(self.root), "push")
        self.assertEqual(code, 1)
        self.assertIn("detached", err)


class CliTests(Base):
    def test_script_runs(self):
        write(self.root, "a.txt")
        done = subprocess.run([sys.executable, str(Path(__file__).with_name("gp.py")), "--repo", str(self.root), "scan"],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0)
        self.assertIn("group root", done.stdout)

    def test_not_a_repo(self):
        code, _, err = run_gp("--repo", self.base, "scan")
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("gp:"))


if __name__ == "__main__":
    unittest.main()
