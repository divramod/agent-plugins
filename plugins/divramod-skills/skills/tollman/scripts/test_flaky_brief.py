"""flaky_brief.py: a load-flaky test's fix goes as a brief into the farmer's delegation ledger, never as a message to
the farmer (plan 0360 step 23, D30); the farmer's `delegation.delegate` is patched: no session, tmux or git."""

import contextlib
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import boss
import delegation
import flaky_brief
import tick

NOW = dt.datetime(2026, 10, 17, 10, 0)


class Place(unittest.TestCase):
    def test_the_action_is_keyed_by_the_test_and_carries_the_evidence(self):
        calls = []
        placed = flaky_brief.place("/x/hal2", "t", "08", "t failed 3x", {"landings": [1]},
                                   delegate=lambda a: calls.append(a) or {"key": a["key"], "state": "running"})
        self.assertEqual(placed["state"], "running")
        (a,) = calls
        self.assertEqual((a["key"], a["duty"], a["kind"], a["slot"]), ("flaky:t", "mtm", "flaky", "08"))
        self.assertEqual(a["brief"], {"test": "t", "why": "t failed 3x", "landings": [1]})
        self.assertIn("disable the load-flaky test t", a["text"])

    def test_the_cli_goes_through_the_farmer_s_delegation_and_fails_when_not_placed(self):
        field = Path(tempfile.mkdtemp())
        for state, want in (("waiting", 0), ("in-hand", 0), ("error", 1)):
            calls = []

            def delegate(a, main, limit, dry, now, values, state=state):
                calls.append((a, main, dry))
                return {"key": a["key"], "state": state}

            out = io.StringIO()
            with mock.patch.object(delegation, "delegate", delegate), \
                    mock.patch.object(flaky_brief.learn.mtm_scan, "main_checkout", return_value=str(field)), \
                    contextlib.redirect_stdout(out):
                code = flaky_brief.main(["place", "--repo", str(field), "--test", "t", "--slot", "08",
                                         "--evidence", json.dumps({"finding": {"test": "t"}})])
            with self.subTest(state=state):
                self.assertEqual(code, want)
                self.assertEqual(json.loads(out.getvalue())["state"], state)
                (a, main, dry), = calls
                self.assertEqual((a["key"], main, dry), ("flaky:t", str(field), False))
                self.assertEqual(a["brief"]["finding"], {"test": "t"})


class Boss(unittest.TestCase):
    def test_the_boss_plans_the_brief_as_a_run_with_a_wake_on_failure_and_sends_nothing(self):
        f = {"kind": "flaky-candidate", "slot": "08", "why": "t failed 3x", "test": "t"}
        snap = {"findings": [f], "queue": [], "worktrees": [], "priority": None,
                "landings": [{"slot": "08", "outcome": "failed", "tests": ["t"], "load_hint": True}]}
        with mock.patch.object(boss.mtm_scan, "DATA", Path(tempfile.mkdtemp())):
            planned = tick.fresh(boss.plan(snap, {"now": NOW, "log": [], "main": "/x/hal2", "top": "/x/tollman"}),
                                 [], NOW)
        (a,) = planned
        self.assertEqual((a["do"], a["kind"], a["key"]), ("run", "flaky", "flaky:t"))
        self.assertTrue(a["argv"][1].endswith("flaky_brief.py"))
        self.assertEqual(a["argv"][a["argv"].index("--repo") + 1], "/x/tollman")
        self.assertEqual(a["argv"][a["argv"].index("--test") + 1], "t")
        self.assertEqual(json.loads(a["argv"][a["argv"].index("--evidence") + 1])["finding"], f)
        self.assertEqual([(w["do"], w["kind"]) for w in a["on_fail"]], [("wake", "flaky-brief-failed")])
        self.assertNotIn("send", [x["do"] for x in planned])


if __name__ == "__main__":
    unittest.main()
