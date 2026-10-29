"""The plan scripts read the pointers from the git dir (`<git-dir>/hal/<name>`) as well as plans/ (hal2 plan 0409 step
12): CURRENT_PLAN through plan.py, planhome, occupied and leave, the servant marker LEAD, the files home still writing
plans/. Scratch repositories only; none needs hal2."""
import unittest

import convert_skip
import occupied
import parallel
import planhome
import test_masterplan as base

SLUG = "0005-demo"


class PointerHomesTest(unittest.TestCase):
    setUp, tearDown = base.MasterplanTest.setUp, base.MasterplanTest.tearDown
    run_plan, plan, write = base.MasterplanTest.run_plan, base.MasterplanTest.plan, base.MasterplanTest.write

    def hide(self, name: str, text: str):
        """The pointer `name` in the git dir only, plans/ without it."""
        file = self.root / ".git" / "hal" / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
        return file

    def test_current_finds_a_pointer_that_sits_only_in_the_git_dir(self):
        self.write(SLUG)
        self.hide("CURRENT_PLAN", SLUG + "\n")
        self.assertFalse((self.root / "plans" / "CURRENT_PLAN").exists())
        found = self.plan("current")
        self.assertEqual((found["slug"], found["current"]), (SLUG, True))
        self.assertEqual(planhome.pointer_slug(self.root), SLUG)
        self.assertEqual(occupied.of(self.root), {"plan": SLUG, "status": "open", "schema": 1})

    def test_the_files_home_writes_plans_not_the_git_dir(self):
        self.plan("new", "Demo plan", "--schema", "1")
        self.assertTrue((self.root / "plans" / "CURRENT_PLAN").is_file())
        self.assertFalse((self.root / ".git" / "hal" / "CURRENT_PLAN").exists())

    def test_leave_removes_a_pointer_in_the_git_dir(self):
        file = self.hide("CURRENT_PLAN", "shots/3/a-shot\n")
        left = self.plan("leave")
        self.assertEqual((left["was"], left["action"]), ("shots/3/a-shot", "deleted"))
        self.assertFalse(file.exists())

    def test_the_servant_marker_is_read_from_the_git_dir(self):
        self.hide("LEAD", f"07 {SLUG} 3\n")
        self.assertEqual(parallel.read_marker(self.root), {"slot": "07", "plan": SLUG, "step": "3"})

    def test_a_field_holding_a_plan_in_its_git_dir_holds_it_for_convert(self):
        field = self.base / "08"
        field.mkdir()
        base.testkit.init_repo(field)
        (field / ".git" / "hal").mkdir()
        (field / ".git" / "hal" / "CURRENT_PLAN").write_text(SLUG + "\n")
        self.assertEqual(convert_skip.SkipSet.read(field).held.get(SLUG), {f"{field.resolve()}:CURRENT_PLAN"})


if __name__ == "__main__":
    unittest.main()
