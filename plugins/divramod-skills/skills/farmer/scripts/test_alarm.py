"""Hal2 plan 0570 steps 4 and 6 (D7, D15): the farmer's ring path (alarm.py). Each of the four stuck cases rings through
`hal2-cli-ring` (faked runner, never the real CLI) and always pushes the reason too (a recorder, never a real notice):
exit 0 is `rung`, 3 `held`, 4 `login`, 1 and another code `failed`, a timeout `timeout`, a missing CLI `missing`; a
case that is not stuck only pushes. The argv carries the reason as one
argument after `--` and nothing else of the user's; the journal line lands in the farmer's log under $FARMER_DIR.
No git: the repo is a plain temp folder."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import alarm
import mtm_scan
import notice
import roles

REAL_RUN = alarm.run  # the default runner, before setUp patches it
SECRET = "hunter2-apple-pw"  # a password in the environment must never reach the argv, the log or the output


class Alarm(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "hal2"
        self.repo.mkdir()
        self.data = self.tmp / "state"
        self.calls, self.sent = [], []
        self.code, self.err, self.out = 0, "", ""
        self.recorded, self.record_error = [], None
        patches = [mock.patch.object(mtm_scan, "DATA", self.data),
                   mock.patch.dict(os.environ, {roles.UNDER_TEST: "1", "FARMER_DIR": str(self.data),
                                                "APPLE_ID_PASSWORD_SEC": SECRET}),
                   mock.patch.object(roles, "git", return_value=""),  # the repo is outside git: no git spawns
                   mock.patch.object(alarm, "run", side_effect=AssertionError("the real ring CLI")),
                   mock.patch.object(notice, "run", side_effect=AssertionError("a real notice")),
                   mock.patch.object(notice, "send", side_effect=self.push)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def runner(self, argv, timeout):
        self.calls.append((argv, timeout))
        return self.code, self.err, self.out

    def rec(self, argv):
        self.recorded.append(argv)
        return self.record_error

    def push(self, title, body):
        self.sent.append((title, body))
        return {"ok": True, "error": None}

    def call(self, case, reason="runner hz01 down 40 min: restart its service", which=lambda _: "/bin/hal2-cli-ring",
             **kw):
        return alarm.alarm(case, reason, str(self.repo), runner=self.runner, which=which, record_fn=self.rec, **kw)

    def journal(self) -> list[dict]:
        path = mtm_scan.state_dir(str(self.repo)) / "log.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_each_stuck_case_rings_and_pushes_the_reason(self):
        reason = "runner hz01 down 40 min: restart its service"
        for case in alarm.STUCK:
            with self.subTest(case=case):
                self.calls.clear()
                self.sent.clear()
                r = self.call(case, reason)
                self.assertEqual((r["ring"], r["rang"], r["exit"], r["stuck"], r["pushed"]),
                                 ("rung", True, 0, True, True))
                self.assertEqual(r["outcome"], "rung, pushed")
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(self.calls[0][1], 60)
                self.assertEqual(self.sent, [(f"farmer-hal2: {case}", reason)])

    def test_a_ring_that_did_not_go_out_still_pushes_and_says_why(self):
        cases = {3: ("held", "held back"), 4: ("login", "login needed"), 1: ("failed", "the ring failed"),
                 7: ("failed", "exit 7")}
        for case in alarm.STUCK:
            for code, (state, why) in cases.items():
                with self.subTest(case=case, code=code):
                    self.sent.clear()
                    self.code, self.err = code, "boom" if code in (1, 7) else ""
                    r = self.call(case)
                    self.assertEqual((r["ring"], r["rang"], r["exit"], r["pushed"]), (state, False, code, True))
                    self.assertEqual(r["outcome"], f"{state}, pushed")
                    self.assertIn(why, r["why"])
                    self.assertEqual(len(self.sent), 1)
                    title, body = self.sent[0]
                    self.assertEqual(title, f"farmer-hal2: {case}")
                    self.assertTrue(body.startswith(r["reason"]))
                    self.assertIn(why, body)

    def test_a_timeout_still_pushes(self):
        self.code, self.err = None, "timed out after 60 s"
        for case in alarm.STUCK:
            with self.subTest(case=case):
                self.sent.clear()
                r = self.call(case)
                self.assertEqual((r["ring"], r["exit"], r["outcome"]), ("timeout", None, "timeout, pushed"))
                self.assertIn("timed out", r["why"])
                self.assertEqual(len(self.sent), 1)

    def test_a_missing_cli_still_pushes_without_running(self):
        for case in alarm.STUCK:
            with self.subTest(case=case):
                self.sent.clear()
                r = self.call(case, which=lambda _: None)
                self.assertEqual((r["ring"], r["outcome"]), ("missing", "missing, pushed"))
                self.assertIn("not installed", r["why"])
                self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.calls, [])

    def test_the_default_runner_counts_a_timeout_and_a_missing_binary_as_failed(self):
        code, err, out = REAL_RUN([str(self.tmp / "no-such-binary")], timeout=5)
        self.assertIsNone(code)
        self.assertIn("FileNotFoundError", err)
        self.assertEqual(out, "")
        with mock.patch.object(alarm.subprocess, "run", side_effect=alarm.subprocess.TimeoutExpired(["x"], 60)):
            self.assertEqual(REAL_RUN(["x"]), (None, "timed out after 60 s", ""))

    def test_a_case_that_is_not_stuck_only_pushes(self):
        r = self.call("landing-done", "wagon 07 is in the barn")
        self.assertEqual((r["outcome"], r["stuck"], r["ring"], r["pushed"]), ("pushed", False, None, True))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.sent, [("farmer-hal2: landing-done", "wagon 07 is in the barn")])

    def test_the_argv_is_the_reason_as_one_argument_and_no_secret(self):
        reason = "--force main red 45 min; field 07 blocked"
        self.call("main-red", reason)
        argv = self.calls[0][0]
        self.assertEqual(argv, ["/bin/hal2-cli-ring", "ring", "--from", "farmer-hal2", "--json", "--no-record", "--",
                                reason])
        self.assertNotIn(SECRET, " ".join(argv))

    def test_the_reason_is_one_line_cut_to_500(self):
        r = self.call("dialog", "line one\nline two " + "x" * 900)
        reason = self.calls[0][0][-1]
        self.assertLessEqual(len(reason), 500)
        self.assertNotIn("\n", reason)
        self.assertEqual(r["reason"], reason)

    def test_the_journal_has_one_alarm_line_without_a_secret(self):
        self.code = 4
        self.call("question-blocks", "field 12 waits for Q3", slot="12")
        lines = self.journal()
        self.assertEqual(len(lines), 1)
        e = lines[0]
        self.assertEqual((e["kind"], e["slot"]), ("alarm", "12"))
        self.assertEqual(e["what"], "question-blocks: field 12 waits for Q3")
        self.assertTrue(e["note"].startswith("login, pushed: login needed"))
        self.assertNotIn(SECRET, json.dumps(lines))

    def test_a_failed_push_is_reported_and_journaled(self):
        self.code = 1
        with mock.patch.object(notice, "send", return_value={"ok": False, "error": "no desktop notification tool"}):
            r = self.call("runner-down")
        self.assertEqual((r["outcome"], r["pushed"]), ("failed, push-failed", False))
        self.assertIn("push failed: no desktop notification tool", self.journal()[0]["note"])

    def test_a_raising_runner_still_pushes(self):
        def broken(argv, timeout):
            raise RuntimeError("bad")
        r = alarm.alarm("dialog", "approve in 07", str(self.repo), runner=broken, which=lambda _: "x")
        self.assertEqual(r["outcome"], "failed, pushed")
        self.assertIn("RuntimeError", r["why"])

    def test_a_rung_ring_and_a_failed_push_still_count_as_reached(self):
        with mock.patch.object(notice, "send", return_value={"ok": False, "error": "x"}), \
                mock.patch.object(alarm, "run", side_effect=lambda argv, timeout: (0, "")), \
                mock.patch.object(alarm.shutil, "which", return_value="/bin/hal2-cli-ring"), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(alarm.main(["dialog", "approve in 07", "--repo", str(self.repo)]), 0)

    def test_the_cli_prints_json_and_exits_by_the_outcome(self):
        out = io.StringIO()
        with mock.patch.object(alarm.shutil, "which", return_value=None), contextlib.redirect_stdout(out):
            code = alarm.main(["runner-down", "hz01 down", "--repo", str(self.repo), "--slot", "-", "--json"])
        self.assertEqual(code, 0)
        doc = json.loads(out.getvalue())
        self.assertEqual((doc["case"], doc["outcome"]), ("runner-down", "missing, pushed"))
        self.assertNotIn(SECRET, out.getvalue())
        with mock.patch.object(notice, "send", return_value={"ok": False, "error": "x"}), \
                mock.patch.object(alarm.shutil, "which", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(alarm.main(["dialog", "approve in 07", "--repo", str(self.repo)]), 1)

    def test_a_muted_ring_is_silent_or_off_and_off_still_pushes(self):
        for word, outcome, rang in (("silent", "silent, pushed", True), ("off", "off, pushed", False)):
            with self.subTest(word=word):
                self.sent.clear()
                self.out = json.dumps({"schema": 1, "outcome": word, "mode": word})
                r = self.call("main-red", "main red 40 min")
                self.assertEqual((r["ring"], r["outcome"], r["rang"], r["exit"], r["pushed"]),
                                 (word, outcome, rang, 0, True))
                self.assertEqual(len(self.sent), 1)
        self.assertIn("(no ring: the ring switch is off)", self.sent[0][1])
        self.out = json.dumps({"schema": 1, "outcome": "rung", "mode": "ring"})
        self.assertEqual(self.call("main-red", "x")["outcome"], "rung, pushed")
        self.out = "not json"
        self.assertEqual(self.call("main-red", "x")["outcome"], "rung, pushed")

    def test_one_notification_with_both_channels_is_recorded_after_ring_and_push(self):
        self.out = json.dumps({"outcome": "off"})
        r = self.call("main-red", "main red 40 min")
        self.assertEqual(self.recorded, [[
            "/bin/hal2-cli-ring", "notifications", "add", "--from", "farmer-hal2", "--role", "farmer", "--farm", "hal2",
            "--case", "main-red", "--channel", "ring:off", "--channel", "push:sent", "--", "main red 40 min"]])
        self.assertIsNone(r["record_error"])

    def test_the_channels_follow_the_ring_state_and_the_push(self):
        for code, channel in ((0, "ring:rung"), (3, "ring:held"), (4, "ring:refused"), (1, "ring:failed")):
            with self.subTest(code=code):
                self.recorded.clear()
                self.code = code
                self.call("dialog", "approve in 07")
                self.assertEqual(self.recorded[0][11:15], ["--channel", channel, "--channel", "push:sent"])
        self.recorded.clear()
        with mock.patch.object(notice, "send", return_value={"ok": False, "error": "x"}):
            self.call("dialog", "approve in 07")
        self.assertIn("push:failed", self.recorded[0])

    def test_a_case_that_is_not_stuck_records_only_the_push(self):
        self.call("landing-done", "wagon 07 is in the barn")
        self.assertEqual(self.recorded[0][9:], ["--case", "landing-done", "--channel", "push:sent", "--",
                                                 "wagon 07 is in the barn"])

    def test_a_missing_cli_or_a_failed_add_never_fails_the_alarm(self):
        r = self.call("main-red", "x", which=lambda _: None)
        self.assertEqual(self.recorded, [])
        self.assertIn("not installed", r["record_error"])
        self.assertEqual((r["outcome"], r["pushed"]), ("missing, pushed", True))
        self.record_error = "exit 2: boom"
        r = self.call("main-red", "x")
        self.assertEqual((r["record_error"], r["outcome"]), ("exit 2: boom", "rung, pushed"))
        broken = mock.Mock(side_effect=RuntimeError("bad"))
        r = alarm.alarm("dialog", "x", str(self.repo), runner=self.runner, which=lambda _: "/bin/c", record_fn=broken)
        self.assertIn("RuntimeError", r["record_error"])
        self.assertTrue(r["pushed"])

    def test_the_default_recorder_reports_an_exit_and_survives_a_raising_run(self):
        with mock.patch.object(alarm, "run", return_value=(0, "", "")):
            self.assertIsNone(alarm.record(["x"]))
        with mock.patch.object(alarm, "run", return_value=(2, "bad flag", "")):
            self.assertIn("exit 2: bad flag", alarm.record(["x"]))
        self.assertIn("AssertionError", alarm.record(["x"]))  # setUp's guard stands in for a real call


if __name__ == "__main__":
    unittest.main()
