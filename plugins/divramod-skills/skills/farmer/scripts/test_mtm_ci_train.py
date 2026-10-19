"""Hal2 plan 0383 step 1 (follow-up in step 4): a train lands on `land/train-<plans>`, which mtm_ci reads as a train,
never as a worktree's slot."""

import unittest

import mtm_ci
from test_mtm_ci import run


class TrainBranch(unittest.TestCase):
    def test_a_train_s_branch_is_a_train_not_a_slot(self):
        """Hal2 plan 0383 step 1: a train lands on `land/train-<plans>`, which is no worktree's landing."""
        self.assertEqual([mtm_ci.slot_of(b) for b in ("land/07", "land/train-0383-0365", "land/train-0383-probe")],
                         ["07", "", ""])
        self.assertEqual([mtm_ci.train_of(b) for b in ("land/train-0383-0365", "train-0383-0365", "land/07",
                                                       "land/train-0383-probe", "", None)],
                         ["train-0383-0365", "train-0383-0365", "", "", "", ""])
        self.assertEqual([mtm_ci.landing_of(b) for b in ("land/07", "land/train-0383", "main")], ["07", "train-0383", ""])
        rows = mtm_ci.summary([run(1, "land/train-0383-0365", status="in_progress", conclusion=""), run(2, "land/05"),
                               run(3, "land/train-0383-probe")], lambda rid: [], 0)
        self.assertEqual([(r["slot"], r["train"], r["outcome"]) for r in rows],
                         [("", "train-0383-0365", "running"), ("05", "", "landed")])
        self.assertEqual(mtm_ci.running_run(rows, "tollman-hal2", "land/train-0383-0365")["url"], "https://x/runs/1")
        self.assertIsNone(mtm_ci.running_run(rows, "tollman-hal2"), "the carrier's slot has no run of its own")
        self.assertIsNone(mtm_ci.running_run(rows, "tollman-hal2", "land/train-0294-09"))


if __name__ == "__main__":
    unittest.main()
