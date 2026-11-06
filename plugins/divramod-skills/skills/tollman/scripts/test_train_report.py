"""Hal2 plan 0695 step 10 (D19): the train's lines by code. A push and a land run start print at once, each once; the
check finds a pushed or ready train shown as waiting. Facts only: the fake queue, train.jsonl, the fake gh runs."""
# enforces .adr/deterministic-first.md and .adr/tollman.md

import datetime as dt
import json
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import roletime
import train_report
import train_state
from test_minute import BRANCH, NAME, Pass

HEAD = "c" * 40


class Report(Pass):
    def setUp(self):
        super().setUp()
        alive = mock.patch.object(train_state, "alive", lambda pid: True)
        alive.start()
        self.addCleanup(alive.stop)

    def push(self, minutes_ago=0):
        at = roletime.utcnow() - dt.timedelta(minutes=minutes_ago)
        train_state.append(str(self.main), "push", "tollman-hal2", at, train=NAME, head=HEAD)

    def log_line(self, **kw):
        with (self.wm_state / "log.jsonl").open("a") as f:
            f.write(json.dumps({"at": (roletime.utcnow() - dt.timedelta(minutes=20)).isoformat(), **kw}) + "\n")

    def test_a_push_prints_its_line_in_the_next_pass_once(self):
        self.train("formed", "started")
        self.push()
        out = self.tick()
        self.assertIn(f"train {NAME} pushed {HEAD[:12]} at ", out)
        self.assertNotIn("pushed", self.tick(), "each line once (its key)")
        self.assertIn(f"report:push:{NAME}:{HEAD[:12]}", [e["key"] for e in self.wm_log()])

    def test_a_land_run_start_prints_once(self):
        self.train("formed", "started")
        self.push()
        first = self.tick()
        self.assertEqual(first.count("land run started: 501 (https://github.com/x/actions/runs/501)"), 1)
        self.assertNotIn("land run started", self.tick())

    def test_the_check_flags_a_pushed_train_with_a_stale_waiting_line_and_no_land_run(self):
        self.gh.runs[:] = []  # the push was 14 min ago and no land run exists
        self.train("formed", "started")
        self.push(14)
        self.log_line(key="x", duty="trains", text=f"train {NAME} should start at the next round")
        lines = self.tick().splitlines()
        self.assertIn(f"report check: train {NAME} pushed 14 min ago, no land run", lines)
        self.assertTrue(any("says waiting" in ln and "landing" in ln for ln in lines), lines)

    def test_a_ready_train_never_reads_waiting_the_check_says_so_after_the_grace(self):
        rows = [{"kind": "formed", "train": NAME, "at": "2026-11-05T10:00:00Z", "cars": []}]
        train = train_state.standing(rows)
        now = dt.datetime(2026, 11, 5, 10, 5, tzinfo=dt.timezone.utc)
        found = train_report.check("/x", rows, train, [], now)
        self.assertEqual([a["text"] for a in found], [f"report check: train {NAME} is formed and ready, not started after 5 min"])
        self.assertEqual(train_report.check("/x", rows, train, [], now, held={"why": "x"}), [], "a hold: not ready")
        young = dt.datetime(2026, 11, 5, 10, 1, tzinfo=dt.timezone.utc)
        self.assertEqual(train_report.check("/x", rows, train, [], young), [], "inside the grace")

    def test_smuggle_mode_prints_no_report(self):
        self.train("formed", "started")
        self.push()
        real = mtm_scan.run_json
        with mock.patch.object(mtm_scan, "run_json", lambda a, cwd=None: {"queue": [], "mode": {"mode": "smuggle"}}
                               if a == mtm_scan.QUEUE else real(a, cwd)):
            self.assertNotIn("pushed", self.tick())


if __name__ == "__main__":
    unittest.main()
