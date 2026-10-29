"""The plan pointers in the git dir (hal2 plan 0409 step 12): the state page reads a field's CURRENT_PLAN and LEAD from
`<git-dir>/hal/` when `plans/` has none."""

import subprocess
import tempfile
import unittest
from pathlib import Path

import farmer_link
import role
import state
import view_foreman


class GitDirPointers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.field = Path(tmp.name).resolve() / "34"
        self.field.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "34"], cwd=self.field, check=True)
        self.hal = self.field / ".git" / "hal"
        self.hal.mkdir()

    def test_current_plan_from_the_git_dir(self):
        self.assertEqual(state.current_plan(str(self.field)), "")
        (self.hal / "CURRENT_PLAN").write_text("0409-plan-store\n")
        self.assertEqual(state.current_plan(str(self.field)), "0409-plan-store")

    def test_lead_in_the_git_dir_makes_a_servant_of_a_field(self):
        self.assertEqual(role.field_role("34", str(self.field)), "foreman")
        (self.hal / "LEAD").write_text("09 0409-plan-store 3\n")
        self.assertEqual(role.field_role("34", str(self.field)), "servant")
        self.assertEqual(farmer_link.foreman_of(self.field), "09")
        self.assertEqual(view_foreman.lead(str(self.field)), ("09", "0409-plan-store", "3"))


if __name__ == "__main__":
    unittest.main()
