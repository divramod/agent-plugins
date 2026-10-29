"""The plan pointers in the git dir (hal2 plan 0409 step 12): a field's pointer there is part of prune's proof, read like
the old `plans/` one, and clearing it removes both places."""

import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import field_facts
import lead_marker
import prune_proof


class GitDirPointers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.field = Path(tmp.name).resolve() / "34"
        self.field.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "34"], cwd=self.field, check=True)
        self.hal = self.field / ".git" / "hal"
        self.hal.mkdir()

    def test_a_pointer_in_the_git_dir_is_read_and_holds_the_field(self):
        (self.hal / "CURRENT_PLAN").write_text("0149-x\nsecond\n")
        self.assertEqual(field_facts.pointer_name(str(self.field)), "0149-x")
        why = prune_proof.unsaved(str(self.field), "34", "34")
        self.assertIn("the CURRENT_PLAN pointer names 0149-x\nsecond", why)

    def test_the_servant_marker_in_the_git_dir_has_its_time(self):
        (self.hal / "LEAD").write_text("09 0275-masterplan 3\n")
        found = prune_proof.marker(str(self.field))
        self.assertEqual((found["slot"], found["plan"]), ("09", "0275-masterplan"))
        self.assertLess(abs(found["at"] - time.time()), 60)

    def test_clearing_removes_the_pointer_from_both_places(self):
        (self.field / "plans").mkdir()
        (self.field / "plans/CURRENT_PLAN").write_text("0149-x\n")
        (self.hal / "CURRENT_PLAN").write_text("0149-x\n")
        lead_marker.pointers.remove(str(self.field), field_facts.POINTER)
        self.assertIsNone(field_facts.pointer_name(str(self.field)))
        self.assertFalse((self.field / "plans/CURRENT_PLAN").exists() or (self.hal / "CURRENT_PLAN").exists())


if __name__ == "__main__":
    unittest.main()
