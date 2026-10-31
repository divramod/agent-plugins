"""Hal2 plan 0530 step 5 for the tollman: its light minute pass (`tollman.tick` -> `minute.light`/`minute.run`) and
its board syncs before and after a round run outside `role_cli.run_tick`'s catch; a crash there counts in the
tollman's tick-health.json like a failed round (the 2nd in a row notifies once), a good round resets it. Its asks and
wakes go through the frame (`acks.plan`, `tick.fresh`): the farmer's test_catch_up covers that path with the
tollman's stamp. No real notice, no git: test_tick_health's setup."""

import argparse
import contextlib
import io
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import board
import minute
import role_cli
import tick
import tick_health
import tollman
import test_tick_health  # its setup, never its tests (a module import: no TestCase here)

GOOD = test_tick_health.GOOD


class TollmanTick(unittest.TestCase):
    wiring = tollman.WIRING
    state = test_tick_health.Rounds.state
    health = test_tick_health.Rounds.health

    def setUp(self):
        test_tick_health.Rounds.setUp(self)
        quiet = mock.patch.object(role_cli, "quiet", return_value=False)
        quiet.start()
        self.addCleanup(quiet.stop)

    def tick_(self, json_out: bool = False) -> tuple[int, str]:
        args = argparse.Namespace(repo=str(self.repo), dry_run=False, json=json_out, all_due=False)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            return tollman.tick(args), err.getvalue()

    def test_a_crashing_minute_pass_counts_and_notifies_at_the_second(self):
        with mock.patch.object(minute, "light", return_value=True), \
                mock.patch.object(minute, "run", side_effect=TypeError("can't compare offset-naive and offset-aware")):
            code, err = self.tick_()
            self.assertEqual((code, self.health()["failures"], self.sent), (5, 1, []))
            self.assertIn("Traceback (most recent call last)", err)
            self.tick_()
        self.assertEqual((self.health()["failures"], len(self.sent)), (2, 1))
        self.assertEqual(self.sent[0], ("hal2 tollman",
                                        "tollman tick failing: TypeError: can't compare offset-naive and offset-aware"))
        with mock.patch.object(minute, "light", side_effect=OSError("light")):
            self.assertEqual(self.tick_()[0], 5)
        self.assertEqual((self.health()["failures"], len(self.sent)), (3, 1), "one notice per streak")

    def test_a_good_minute_pass_resets_nothing_a_good_round_does(self):
        with mock.patch.object(minute, "light", return_value=True), mock.patch.object(minute, "run", return_value=0):
            role_cli.health(str(self.repo), self.wiring, KeyError("x"))
            self.assertEqual(self.tick_()[0], 0)
        self.assertEqual(self.health()["failures"], 1)
        with mock.patch.object(board, "sync", return_value=[]), mock.patch.object(tick, "run", return_value=GOOD):
            self.assertEqual(self.tick_(json_out=True)[0], 0)
        self.assertEqual(self.health()["failures"], 0)

    def test_a_failing_board_sync_counts_once_per_tick(self):
        with mock.patch.object(board, "sync", side_effect=OSError("board.jsonl: read-only")), \
                mock.patch.object(tick, "run", return_value=GOOD):
            self.assertEqual(self.tick_(json_out=True)[0], 0)
            self.assertEqual(self.health()["failures"], 1)
            self.tick_(json_out=True)
        self.assertEqual((self.health()["failures"], len(self.sent)), (2, 1))
        self.assertTrue(self.health()["error"].startswith("BoardFailed: board messages and acks: "))
        self.assertTrue((self.state / tick_health.FILE).exists())


if __name__ == "__main__":
    unittest.main()
