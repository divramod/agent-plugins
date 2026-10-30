"""The plan pointers in the git dir (hal2 plan 0409 step 12): the tollman reads CURRENT_PLAN and LEAD from `<git-dir>/hal/`
as from the old `plans/`, writes a train's title to `plans/` in the files home and drops both places."""

import subprocess
import tempfile
import unittest
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import git_seed
import frozen
import train_wt
import trains_sort
import transplant_mark


def git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class GitDirPointers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        git_seed.guard(self)
        self.top = Path(tmp.name).resolve() / "tollman-hal2"
        self.top.mkdir()
        git_seed.grow(self.top, "test_tollman_pointers.GitDirPointers", lambda: git(self.top, "init", "-q", "-b", "main"))
        self.hal = self.top / ".git" / "hal"
        self.hal.mkdir()

    def test_current_plan_and_lead_are_read_from_the_git_dir(self):
        (self.hal / "CURRENT_PLAN").write_text("transplant-from-07\n\n")
        (self.hal / "LEAD").write_text("07 0001-x 2\n")
        self.assertEqual(trains_sort.current_plan(str(self.top)), "transplant-from-07")
        self.assertTrue(trains_sort.servant(str(self.top)))
        mark = transplant_mark.from_marker(str(self.top))
        self.assertEqual((mark.state, mark.src), ("prepared", "07"))

    def test_a_trains_title_is_written_to_plans_in_the_files_home_and_dropped_from_both(self):
        frozen.write_current(str(self.top), [{"field": "07", "plan": "0001-x"}, {"field": "09"}], True)
        self.assertEqual((self.top / "plans/CURRENT_PLAN").read_text(), "yard + 0001-x + 09\n")
        (self.hal / "CURRENT_PLAN").write_text("stale\n")
        frozen.POINTERS.remove(str(self.top), frozen.CURRENT)
        self.assertFalse((self.top / "plans/CURRENT_PLAN").exists() or (self.hal / "CURRENT_PLAN").exists())
        self.assertFalse(frozen.POINTERS.exists(str(self.top), frozen.CURRENT))


if __name__ == "__main__":
    unittest.main()
