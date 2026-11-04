import tempfile
import unittest
from pathlib import Path

import lessons


class LessonsTest(unittest.TestCase):
    def test_seeds_listed(self):
        self.assertEqual([e["class"] for e in lessons.entries()],
                         ["done-not-hitched", "pushing", "landing-per-plan"])

    def test_add_and_read_back(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "lessons.md"
            e = lessons.add("blocked-plan", "ask  once", "0514", f, today="2026-11-03")
            self.assertEqual(lessons.entries(f), [e])
            self.assertIn("## blocked-plan", f.read_text())
            with self.assertRaises(lessons.LessonError):
                lessons.add("blocked-plan", "ask once", "", f)
            with self.assertRaises(lessons.LessonError):
                lessons.add("Bad Class", "x", "", f)

    def test_json(self):
        self.assertIn('"schema": 1', lessons.show(as_json=True))
