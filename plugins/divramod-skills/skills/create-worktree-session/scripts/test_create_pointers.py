"""The servant's pointers (hal2 plan 0409 step 12): in the files home create.py still writes plans/LEAD and
plans/CURRENT_PLAN; a LEAD in the git dir marks a field a servant's."""
import subprocess
import tempfile
import unittest
from pathlib import Path

import create


class Pointers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name).resolve()
        subprocess.run(["git", "init", "-q"], cwd=self.folder, check=True)

    def test_the_files_home_gets_plans_files(self):
        create.write_lead(self.folder, "07 0376-one-plan-shape 02-readers")
        self.assertEqual((self.folder / "plans/LEAD").read_text(), "07 0376-one-plan-shape 02-readers\n")
        self.assertEqual((self.folder / "plans/CURRENT_PLAN").read_text(), "0376-one-plan-shape\n")
        self.assertFalse((self.folder / ".git/hal").exists())

    def test_a_lead_in_the_git_dir_marks_a_servants_field(self):
        entry = {"path": str(self.folder)}
        self.assertIsNone(create.work(entry, None))
        (self.folder / ".git/hal").mkdir()
        (self.folder / ".git/hal/LEAD").write_text("07 0376-one-plan-shape 02-readers\n")
        self.assertEqual(create.work(entry, None), "a servant's field (plans/LEAD)")
        self.assertIsNone(create.work(entry, None, servant=True))


if __name__ == "__main__":
    unittest.main()
