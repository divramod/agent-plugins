"""Hal2 plan 0383 step 1 (follow-up in step 4): a train lands on `land/train-<plans>`, so the carrier's row shows the
runs of the branch its ticket names, over test_state's fixture (the outside tools are mocked)."""

import os
import unittest

from test_state import Fixture


class TrainRuns(Fixture):
    def test_a_train_s_run_belongs_to_the_carrier_whose_ticket_lands_on_it(self):
        real = os.path.realpath
        queue = [{"slot": "02", "worktree": real(self.wt / "02"), "position": 0, "holding": True, "state": "active",
                  "land_ref": "land/train-0383-0365"},
                 {"slot": "10", "worktree": real(self.wt / "10"), "position": 1, "holding": False, "state": "waiting",
                  "land_ref": None}]
        runs = [{"workflow": "merge-to-main", "status": "in_progress", "branch": "land/train-0383-0365", "sha": "a", "url": "u1"},
                {"workflow": "merge-to-main", "status": "queued", "branch": "land/train-0294-09", "sha": "b", "url": "u2"}]
        self.set_tools(queue=queue, runs=runs)
        rows = self.rows()
        self.assertEqual([c["url"] for c in rows["02"]["ci"]], ["u1"], "the ticket's own train branch only")
        self.assertEqual(rows["10"]["ci"], [])


if __name__ == "__main__":
    unittest.main()
