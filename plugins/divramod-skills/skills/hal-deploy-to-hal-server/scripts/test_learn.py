import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import learn
import testkit

SKILL = Path(__file__).resolve().parent.parent


class LearnTest(unittest.TestCase):
    def skill_copy(self):
        tmp = testkit.scratch() / "skill"
        shutil.copytree(SKILL, tmp, ignore=shutil.ignore_patterns("__pycache__"))
        return tmp

    def test_scaffold_writes_check_test_and_line_and_the_test_fails_until_written(self):
        skill = self.skill_copy()
        files = learn.scaffold("made-up-problem", "a problem no check knows", skill)
        self.assertEqual(len(files), 3)
        self.assertIn("made-up-problem", (skill / "references/problems.md").read_text())
        proc = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_check_made_up_problem"], cwd=skill / "scripts",
                              capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("write the test", proc.stderr)

    def test_existing_check_and_bad_slug_are_refused(self):
        skill = self.skill_copy()
        with self.assertRaises(FileExistsError):
            learn.scaffold("dockerfile-missing", "", skill)
        for slug in ("Bad_Slug", "../x", "a b", ""):
            with self.subTest(slug=slug), self.assertRaises(ValueError):
                learn.scaffold(slug, "", skill)

    def test_brief_names_the_files_and_writes_nothing(self):
        text = learn.brief("made-up-problem", "a problem no check knows")
        self.assertIn("checks/made_up_problem.py", text)
        self.assertIn("test_check_made_up_problem.py", text)
        self.assertFalse((SKILL / "scripts/checks/made_up_problem.py").exists())


if __name__ == "__main__":
    unittest.main()
