"""A LEAD in the git dir marks a field a servant's (create.py writes none itself since plan 0594: servant assign)."""
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

    def test_a_lead_in_the_git_dir_marks_a_servants_field(self):
        entry = {"path": str(self.folder)}
        self.assertIsNone(create.work(entry, None))
        (self.folder / ".git/hal").mkdir()
        (self.folder / ".git/hal/LEAD").write_text("07 0376-one-plan-shape 02-readers\n")
        self.assertEqual(create.work(entry, None), "a servant's field (plans/LEAD)")
        self.assertIsNone(create.work(entry, None, servant=True))


if __name__ == "__main__":
    unittest.main()
