"""planhome.py (hal2 plan 0409 step 8): the files home asks no CLI and changes nothing; a view names its files as
`plans/<...>`; a stable view keeps a copy with edits of its own."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import planhome


class Home(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="planhome-")) / "repo"
        self.addCleanup(shutil.rmtree, self.tmp.parent, True)
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        planhome._HOMES.clear()

    def test_a_checkout_without_a_farm_is_the_files_home_without_a_cli_call(self):
        with mock.patch.object(planhome, "run", side_effect=AssertionError("no CLI call")):
            self.assertIsNone(planhome.home(self.tmp))
            self.assertIsNone(planhome.sync(self.tmp, "step-done"))
        self.assertEqual(planhome.plans_dir(self.tmp), self.tmp / "plans")
        self.assertEqual(planhome.rel(self.tmp / "plans" / "0001-a" / "plan.md", self.tmp),
                         os.path.join("plans", "0001-a", "plan.md"))

    def test_a_farm_in_the_files_home_or_without_an_answer_reads_the_files(self):
        subprocess.run(["git", "-C", str(self.tmp), "config", "hal.farm", "f-1"], check=True)
        with mock.patch.object(planhome, "run", return_value={"home": "files", "edit": "/x"}):
            self.assertIsNone(planhome.home(self.tmp))
        planhome._HOMES.clear()
        with mock.patch.object(planhome, "run", side_effect=planhome.HomeError("old binary")):
            self.assertIsNone(planhome.home(self.tmp))
        planhome._HOMES.clear()
        with mock.patch.object(planhome, "run", return_value={"home": "store", "edit": "/x"}):
            self.assertEqual(planhome.home(self.tmp)["edit"], "/x")

    def test_a_view_names_its_files_as_the_checkout_does(self):
        view = self.tmp.parent / "view"
        planhome.register(self.tmp, view)
        self.addCleanup(planhome.register, self.tmp, None)
        self.assertEqual(planhome.plans_dir(self.tmp), view)
        self.assertEqual(planhome.rel(view / "0001-a" / "steps" / "1.md", self.tmp), "plans/0001-a/steps/1.md")
        self.assertTrue(planhome.inside(view / "0001-a" / "plan.md", self.tmp))
        self.assertIn("plan.py apply", planhome.store_note(self.tmp, "0001"))

    def test_a_stable_view_keeps_an_edited_copy(self):
        edit = self.tmp.parent / "edit"
        view = planhome.View(self.tmp, {"edit": str(edit)}, stable=True)
        (edit / "0001-a").mkdir(parents=True)
        (edit / "0001-a" / "plan.md").write_text("one\n")
        view.snap["0001-a"] = planhome.digest(edit / "0001-a")
        self.assertFalse(view.edited("0001-a"))
        (edit / "0001-a" / "plan.md").write_text("two\n")
        self.assertTrue(view.edited("0001-a"))
        with mock.patch.object(planhome, "run", side_effect=AssertionError("no render over an edit")):
            self.assertEqual(view.render("1"), "0001-a")
        self.assertEqual(view.changed(), ["0001-a"])

    def test_pointer_slugs(self):
        (self.tmp / "plans").mkdir()
        (self.tmp / "plans" / "CURRENT_PLAN").write_text("0007-x\n")
        (self.tmp / "plans" / "PREVIOUS_PLAN").write_text("shots/3/a-shot\n")
        self.assertEqual(planhome.pointer_slug(self.tmp), "0007-x")
        self.assertEqual(planhome.pointer_slug(self.tmp, "PREVIOUS_PLAN"), "")


if __name__ == "__main__":
    unittest.main()
