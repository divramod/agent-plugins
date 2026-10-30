"""The plan pointers in the git dir (hal2 plan 0409 step 12): LEAD and CURRENT_PLAN kept in `<git-dir>/hal/` (a
store-home farm) are read by the farmer's scans as the old `plans/` ones are; a worktree's pointer sits in its admin dir."""

import subprocess
import tempfile
import unittest
from pathlib import Path

import unit_scripts  # noqa: F401  (the skills unit's scripts/ on the import path: git_seed)
import decision_check
import delegation
import lead_marker
import git_seed
import mtm_scan
from test_farmer import git


class GitDirPointers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.main = Path(self.tmp.name) / "hal2"
        self.field = Path(self.tmp.name) / "wt/34"
        git_seed.guard(self)
        git_seed.grow(self.tmp.name, "test_farmer_pointers.GitDirPointers", self.grow)

    def grow(self):
        """The repository and its field 34, grown once and shared by every process (git_seed)."""
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        git(self.main, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "root")
        git(self.main, "worktree", "add", "-q", "-b", "34", str(self.field), "main")

    def admin(self, path: Path) -> Path:
        found = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=path, capture_output=True, text=True)
        return Path(found.stdout.strip()) / "hal"

    def put(self, path: Path, name: str, text: str) -> None:
        folder = self.admin(path)
        folder.mkdir(exist_ok=True)
        (folder / name).write_text(text + "\n")

    def test_a_worktrees_lead_in_its_admin_dir_marks_it_a_servant(self):
        self.assertIsNone(lead_marker.marker(self.field))
        self.put(self.field, "LEAD", "09 0275-masterplan 3")
        self.assertEqual(lead_marker.marker(self.field), {"slot": "09", "plan": "0275-masterplan", "step": "3"})
        self.assertFalse((self.field / "plans/LEAD").exists())
        self.assertFalse(delegation.servant_slot("34", str(self.field)))
        self.assertTrue(delegation.servant_slot("34", str(self.main)))

    def test_current_plan_in_the_git_dir_wins_over_the_old_place(self):
        (self.field / "plans").mkdir()
        (self.field / "plans/CURRENT_PLAN").write_text("0001-old\n")
        self.assertEqual(lead_marker.current_plan(self.field), "0001-old")
        self.put(self.field, "CURRENT_PLAN", "0409-plan-store")
        self.assertEqual(lead_marker.current_plan(self.field), "0409-plan-store")
        self.assertEqual(mtm_scan.worktree_entry({"path": str(self.field)}, {}, "main", 0)["plan"], "0409-plan-store")

    def test_a_main_checkouts_pointer_in_its_git_dir(self):
        self.put(self.main, "CURRENT_PLAN", "0409-plan-store")
        self.assertEqual(lead_marker.current_plan(self.main), "0409-plan-store")
        self.assertEqual(decision_check.pointers.read(self.main, "CURRENT_PLAN"), "0409-plan-store")


if __name__ == "__main__":
    unittest.main()
