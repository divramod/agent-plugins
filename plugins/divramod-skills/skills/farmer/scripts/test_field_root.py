"""Only fields are judged by the merge-to-main scan (plan 0490 step 11): L89's scratch worktree and L96's train
worktree are never orphans."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import field_root
import mtm_scan as scan

HOME = Path("/Users/u")
MAIN = str(HOME / "a/hal2")
ROOT = HOME / ".hal/git/worktree/hal2"


class IsField(unittest.TestCase):
    def test_a_numbered_field_in_the_root_is_one(self):
        self.assertTrue(field_root.is_field({"path": str(ROOT / "17"), "branch": "17"}, MAIN))

    def test_l89_a_scratch_worktree_outside_the_root_is_none(self):
        trial = "/private/tmp/claude-501/-Users-u--hal-git-worktree-hal2-17/x/scratchpad/trial"
        self.assertFalse(field_root.is_field({"path": trial}, MAIN), "detached, 67 commits off main")
        self.assertFalse(field_root.is_field({"path": str(HOME / ".hal/git/worktree/other/03"), "branch": "03"},
                                             MAIN), "another farm's root")

    def test_l96_a_train_worktree_is_none_by_branch_or_name(self):
        self.assertFalse(field_root.is_field({"path": str(ROOT / "trainfix"), "branch": "tollman-train-0432"}, MAIN))
        self.assertFalse(field_root.is_field({"path": str(ROOT / "tollman-train-0432"), "branch": "x"}, MAIN))

    def test_beside_or_inside_the_main_checkout_still_counts(self):
        self.assertTrue(field_root.is_field({"path": str(HOME / "a/04"), "branch": "04"}, MAIN))
        self.assertTrue(field_root.is_field({"path": MAIN + "/04", "branch": "04"}, MAIN))


class Scan(unittest.TestCase):
    def test_the_snapshot_judges_neither_a_scratch_trial_nor_a_train_worktree(self):
        with tempfile.TemporaryDirectory() as d:
            main, root = Path(d) / "hal2", Path(d) / ".hal/git/worktree/hal2"
            wts = [{"path": str(root / "04"), "branch": "04"},
                   {"path": str(Path(d) / "tmp/scratchpad/trial"), "branch": None},
                   {"path": str(root / "trainfix"), "branch": "tollman-train-0432"}]
            for w in wts:
                Path(w["path"]).mkdir(parents=True)
            agents = lambda args, cwd=None: {"agents": []} if args[:2] == ["hal2-cli-agents", "list"] else None
            with mock.patch.object(scan, "run", return_value=""), mock.patch.object(scan, "run_json", agents), \
                    mock.patch.object(scan, "worktrees", return_value=wts), \
                    mock.patch.object(scan, "unmerged", return_value=15), \
                    mock.patch.object(scan.mtm_ci, "ci_mode", return_value=False), \
                    mock.patch.object(scan, "state_dir", return_value=Path(d) / "state"):
                got = scan.snapshot(str(main), 24, fetch=False)
        self.assertEqual([w["slot"] for w in got["worktrees"]], ["04"])
        self.assertEqual([(f["kind"], f["slot"]) for f in got["findings"]], [("work-without-agent", "04")])


if __name__ == "__main__":
    unittest.main()
