"""Hal2 plan 0349 step 10 (D6): `farmer.py silence`. A silenced real round prints one table line with a "joined"
column (the fields it acted on) and nothing else; a dry run and --json stay full."""

import contextlib
import io
import json
import unittest
from unittest import mock

import farmer
import role_cli
import silence
import tick
from test_farmer import Repo

ROUND = {"dry": False, "due": [{"name": "duty:lead"}, {"name": "duty:ci"}], "planned": [],
         "done": [{"duty": "frame", "kind": "stay-current", "slot": "-", "do": "run"},
                  {"duty": "lead", "kind": "idle", "slot": "07", "do": "send"},
                  {"duty": "lead", "kind": "idle", "slot": "09", "do": "relay"},
                  {"duty": "lead", "kind": "ran", "slot": "-", "do": "ran"}],
         "woke": {"pending": 1, "woken": False}, "timing": {"total": 1.0}}


class Silence(Repo):
    def call(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()), \
                mock.patch.object(role_cli.shutil, "which", return_value="/bin/x"):
            code = farmer.main([*argv, "--repo", str(self.slot)])
        return code, buf.getvalue()

    def test_the_verbs_set_and_clear_the_marker(self):
        self.assertEqual(self.call("silence"), (0, "farmer: silent\n"))
        self.assertTrue(silence.on(str(self.slot)))
        self.assertEqual(self.call("unsilence"), (0, "farmer: not silent\n"))
        self.assertFalse(silence.on(str(self.slot)))

    def test_a_silenced_round_is_one_table_line_with_joined(self):
        self.call("mode", "timer")
        with mock.patch.object(tick, "run", return_value=dict(ROUND)):
            self.call("silence")
            code, out = self.call("tick")
            self.assertEqual((code, out), (0, "| farmer | 2 due, 3 done, 1 for judgment | joined 07, 09 |\n"))
            self.assertEqual(self.call("tick", "--json")[1].count('"due"'), 1, "json stays full")
            self.call("unsilence")
            self.assertIn("farmer tick (round): 2 due", self.call("tick")[1])

    def test_a_dry_run_stays_full(self):
        self.call("silence")
        with mock.patch.object(tick, "run", return_value=dict(ROUND, dry=True)):
            self.assertIn("farmer tick (dry run)", self.call("tick", "--dry-run")[1])

    def test_a_round_that_stopped_is_one_line_with_its_problem(self):
        self.assertEqual(silence.round_lines({"problem": "not the farmer's worktree"}, farmer.WIRING),
                         ["| farmer | problem: not the farmer's worktree | joined - |"])


if __name__ == "__main__":
    unittest.main()
