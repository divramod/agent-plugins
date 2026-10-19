"""Hal2 plan 0383 step 16 (D16): a foreman starts in any free field 00-99, lowest first; a field holding plans/LEAD is a
servant's and is never taken. (Plan 0333 step 9 had stopped foremen at field 29.)"""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import delegation
from test_delegation import MAIN, NOW, Ledger, flaky


class ForemanFields(Ledger):
    def create_says(self, code, out):
        """create.py answers `(code, out)`, every other call as in Ledger.setUp."""
        base = delegation.call

        def call(argv, cwd):
            if argv[:2] == delegation.CREATE:
                self.calls.append(argv)
                return code, out
            return base(argv, cwd)
        p = mock.patch.object(delegation, "call", call)
        p.start()
        self.addCleanup(p.stop)

    def marked(self, name):
        """A worktree folder holding a foreman's `plans/LEAD`."""
        d = Path(tempfile.mkdtemp()) / name
        (d / "plans").mkdir(parents=True)
        (d / "plans" / "LEAD").write_text("07 0383-train-rules 16\n")
        return str(d)

    def test_create_gets_the_whole_range_so_field_30_is_taken_when_00_29_are_busy(self):
        self.create_says(0, json.dumps({"slot": "30"}))
        r = delegation.delegate(flaky(), MAIN, 5, False, NOW)
        self.assertEqual((r["state"], r["slot"], r["how"]), ("running", "30", "new"))
        (create,) = [c for c in self.calls if c[:2] == delegation.CREATE]
        self.assertEqual(create[create.index("--from"):create.index("--from") + 4], ["--from", "00", "--to", "99"])

    def test_the_limit_bypass_hands_create_the_same_range(self):
        with mock.patch.object(delegation, "machine_load", return_value=0.0):
            r = delegation.delegate(flaky(), MAIN, 999, True, NOW)
        argv = r["calls"][1]
        self.assertEqual(argv[argv.index("--from") + 1:argv.index("--from") + 4], ["00", "--to", "99"])

    def test_all_fields_busy_nothing_starts_and_the_action_waits_with_the_reason(self):
        self.create_says(delegation.NO_FREE_EXIT, "")
        r = delegation.delegate(flaky(), MAIN, 5, False, NOW)
        self.assertEqual((r["state"], r["reason"]), ("waiting", "no free field 00-99"))
        entry = delegation.ledger(MAIN)["flaky:t"]
        self.assertEqual((entry["state"], entry["reason"]), ("waiting", "no free field 00-99"))
        again = delegation.follow_up(MAIN, {}, 5, False, NOW + dt.timedelta(minutes=5))
        self.assertEqual([(d["state"], d["reason"]) for d in again], [("waiting", "no free field 00-99")])

    def test_a_waiting_delegation_starts_once_a_field_is_free(self):
        self.create_says(delegation.NO_FREE_EXIT, "")
        self.assertEqual(delegation.delegate(flaky(), MAIN, 5, False, NOW)["state"], "waiting")
        self.create_says(0, json.dumps({"slot": "07"}))
        later = delegation.follow_up(MAIN, {}, 5, False, NOW + dt.timedelta(minutes=5))
        self.assertEqual([(d["state"], d["slot"]) for d in later], [("running", "07")])

    def test_a_free_session_in_field_30_is_reused_after_the_lower_ones(self):
        self.free = [{"slot": "44", "panes": ["%44"]}, {"slot": "30", "panes": ["%30"]},
                     {"slot": "main", "panes": ["%1"]}]
        with mock.patch.object(delegation.deliver, "send", return_value=None) as send:
            r = delegation.delegate(flaky(), MAIN, 5, False, NOW)
        self.assertEqual((r["slot"], r["how"]), ("30", "free"))
        self.assertEqual(send.call_args.args[0], "%30")

    def test_a_free_session_in_a_field_holding_plans_lead_is_never_taken(self):
        self.create_says(0, json.dumps({"slot": "07"}))
        self.free = [{"slot": "31", "panes": ["%31"], "worktree": self.marked("31")},
                     {"slot": "05", "panes": ["%5"], "worktree": self.marked("05")}]
        with mock.patch.object(delegation.deliver, "send", return_value=None) as send:
            r = delegation.delegate(flaky(), MAIN, 5, False, NOW)
        send.assert_not_called()
        self.assertEqual((r["slot"], r["how"]), ("07", "new"))

    def test_servant_slot_is_any_numbered_field_without_a_marker(self):
        for slot in ("00", "07", "29", "30", "44", "99"):
            self.assertTrue(delegation.servant_slot(slot), slot)
        for slot in ("main", "farmer-hal2", "1", "100", None):
            self.assertFalse(delegation.servant_slot(slot), slot)
        self.assertFalse(delegation.servant_slot("30", self.marked("30")))
        self.assertTrue(delegation.servant_slot("30", tempfile.mkdtemp()))


if __name__ == "__main__":
    unittest.main()
