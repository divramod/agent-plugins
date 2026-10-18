import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import page
import view_goals
import views

FILES = {"mayor": "1-year.md", "lord": "3-5-years.md", "pope": "life.md"}


class Goals(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.places = {"mayor": self.tmp / "village", "lord": self.tmp / "city", "pope": self.tmp / "planet"}
        env = {"HAL_VILLAGE": str(self.places["mayor"]), "HAL_CITY": str(self.places["lord"]),
               "HAL_PLANET": str(self.places["pope"])}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)

    def build(self, who):
        ctx = {"role": who, "repo": "x", "checkout": "main"}
        title, sections = views.build(who, {"rows": [], "default": "main"}, ctx)
        return title, sections, page.render(title, sections)

    def write(self, who, text):
        path = self.places[who] / "office" / "goals" / FILES[who]
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_registered_for_the_three_roles(self):
        for who in FILES:
            self.assertIs(views.VIEWS[who], view_goals.view)

    def test_empty_state_names_the_file_and_creates_nothing(self):
        for who, name in FILES.items():
            _, _, out = self.build(who)
            self.assertIn("No goals written yet", out)
            self.assertIn(str(self.places[who] / "office" / "goals" / name), out)
            self.assertFalse(self.places[who].exists())

    def test_lists_the_goal_lines_with_nesting_and_mtime(self):
        path = self.write("lord", "# Goals\nintro\n- Ship hal9k\n  - beta first\n- Learn <b>Rust</b>\n")
        _, sections, out = self.build("lord")
        self.assertEqual(sections[0]["items"], ["Ship hal9k", "  beta first", "Learn <b>Rust</b>"])
        self.assertIn("Learn &lt;b&gt;Rust&lt;/b&gt;", out)
        self.assertNotIn("intro", out)
        self.assertIn(str(path), out)
        self.assertIn("changed 20", out)

    def test_each_role_reads_only_its_own_file(self):
        self.write("mayor", "- mayor goal\n")
        self.write("pope", "- pope goal\n")
        self.assertIn("mayor goal", self.build("mayor")[2])
        self.assertNotIn("pope goal", self.build("mayor")[2])
        self.assertIn("No goals written yet", self.build("lord")[2])

    def test_a_file_without_goal_lines_is_the_empty_state(self):
        self.write("pope", "# Life\nnothing yet\n")
        self.assertIn("No goals written yet", self.build("pope")[2])

    def test_no_farm_data(self):
        data = {"rows": [{"cells": ["07", "plan", "1/2", "busy", "-"]}], "default": "main"}
        _, sections = views.build("mayor", data, {"role": "mayor", "repo": "x", "checkout": "main"})
        self.assertEqual(len(sections), 1)
        self.assertNotIn("plan", str(sections))


if __name__ == "__main__":
    unittest.main()
