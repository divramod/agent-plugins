"""`due.py check` names the prune timer (hal2 plan 0695 step 14): its last tick and round, DEAD when it stopped."""

import tempfile
import unittest
from pathlib import Path

import timer_state as ts


class TimerLine(unittest.TestCase):
    def test_no_state_a_running_round_a_red_round_and_a_dead_timer(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.assertIn("no state", ts.line(d))
            state = {"label": "local.farmer.prune.hal2", "seen": {"ticked": 1000.0},
                     "round": {"id": 1, "pid": 1, "started": 900.0, "ended": None, "rc": None}}
            ts.save(d, state)
            self.assertIn("local.farmer.prune.hal2, last tick 1 min ago, round running for 2 min", ts.line(d, 1060.0))
            state["round"].update(ended=950.0, rc=1)
            ts.save(d, state)
            self.assertIn("last round RED (rc 1)", ts.line(d, 1100.0))
            self.assertIn("DEAD", ts.line(d, 1000.0 + ts.DEAD_AFTER + 1))


if __name__ == "__main__":
    unittest.main()
