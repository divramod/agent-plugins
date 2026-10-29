"""pointers.py: the git dir wins, the old place is the fallback, a write follows the home (hal2 plan 0409 step 12)."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pointers  # noqa: E402


class Pointers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        (self.root / ".git").mkdir(parents=True)

    def test_the_git_dir_wins_and_the_old_place_is_read_as_a_fallback(self):
        self.assertEqual(pointers.read(self.root, "CURRENT_PLAN"), "")
        (self.root / "plans").mkdir()
        (self.root / "plans/CURRENT_PLAN").write_text("0001-old\n")
        self.assertEqual(pointers.read(self.root, "CURRENT_PLAN"), "0001-old")
        (self.root / ".git/hal").mkdir()
        (self.root / ".git/hal/CURRENT_PLAN").write_text("0002-new\n")
        self.assertEqual(pointers.read(self.root, "CURRENT_PLAN"), "0002-new")
        self.assertEqual(pointers.path(self.root, "CURRENT_PLAN"), self.root / ".git/hal/CURRENT_PLAN")
        pointers.remove(self.root, "CURRENT_PLAN")
        self.assertFalse(pointers.exists(self.root, "CURRENT_PLAN"))

    def test_a_write_follows_the_home(self):
        with mock.patch.object(pointers, "in_store", return_value=False):
            self.assertEqual(pointers.write(self.root, "LEAD", "07 0294-x 3"), self.root / "plans/LEAD")
        self.assertEqual((self.root / "plans/LEAD").read_text(), "07 0294-x 3\n")
        with mock.patch.object(pointers, "in_store", return_value=True):
            self.assertEqual(pointers.write(self.root, "LEAD", "08 0294-x 4"), self.root / ".git/hal/LEAD")
        self.assertFalse((self.root / "plans/LEAD").exists(), "the old copy goes")
        self.assertEqual(pointers.read(self.root, "LEAD"), "08 0294-x 4")

    def test_a_worktree_reads_the_folder_its_dot_git_names(self):
        admin = Path(self.tmp.name) / "main/.git/worktrees/02"
        (admin / "hal").mkdir(parents=True)
        (admin / "hal/CURRENT_PLAN").write_text("0003-x\n")
        field = Path(self.tmp.name) / "02"
        field.mkdir()
        (field / ".git").write_text(f"gitdir: {admin}\n")
        self.assertEqual(pointers.read(field, "CURRENT_PLAN"), "0003-x")

    def test_the_shell_entry(self):
        (self.root / ".git/hal").mkdir()
        (self.root / ".git/hal/LEAD").write_text("07 a 1\n")
        script = Path(pointers.__file__)
        done = subprocess.run([sys.executable, str(script), "read", str(self.root), "LEAD"], capture_output=True,
                              text=True)
        self.assertEqual(done.stdout, "07 a 1\n")
        done = subprocess.run([sys.executable, str(script), "exists", str(self.root), "CURRENT_PLAN"])
        self.assertEqual(done.returncode, 1)


if __name__ == "__main__":
    unittest.main()
