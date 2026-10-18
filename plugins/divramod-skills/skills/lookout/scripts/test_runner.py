"""Tests of runner.py and watchstate.py: fake checks per exit code, a fake `claude` (never the real one)."""

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fakes
import paths
import runner
import watchstate

NOW = dt.datetime(2026, 10, 14, 11, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
FOUND = """\
    import json, sys
    for i in (1, 2, 1):
        print(json.dumps({"id": f"email-{i}", "summary": f"mail {i}"}))
    sys.exit(%d)
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.farm = self.tmp / "farm"
        self.farm.mkdir()
        self.claude = fakes.fake_claude(self.tmp / "bin")
        self.log = self.tmp / "log.jsonl"
        self.env = fakes.base_env()
        patch = mock.patch.dict(os.environ, {"LOOKOUT_CLAUDE": self.claude, "LOOKOUT_STATE_DIR": str(self.tmp / "st"),
                                             "LOOKOUT_DIR": str(self.tmp / "cfg")})
        patch.start()
        self.addCleanup(patch.stop)

    def record(self, body, **keys):
        return dict({"id": "replies", "title": "Replies", "farm": str(self.farm),
                     "check": fakes.fake_check(self.tmp, "check", body)}, **keys)

    def run_watch(self, record, now=NOW, **kw):
        return runner.run_watch(record, "jobsearch", self.tmp / "w", now=now, env=self.env, log=self.log, **kw)

    def claude_calls(self):
        return fakes.calls(self.tmp / "bin")


class CheckContractTest(Base):
    def test_quiet_run_calls_no_claude(self):
        result = self.run_watch(self.record("print('3 mails, none new')\n", judge="Classify."))
        self.assertEqual(result["outcome"], "quiet")
        self.assertEqual(result["record"], {"last_run": NOW.isoformat(), "last_result": "3 mails, none new",
                                            "state": "quiet"})
        self.assertEqual(result["finds"], [])
        self.assertEqual(self.claude_calls(), [])
        (line,) = paths.read_log(self.log)
        self.assertEqual((line["kind"], line["outcome"], line["code"]), ("check", "quiet", 0))

    def test_contract_env_cwd_stdin_and_since_in_utc(self):
        body = """\
            import json, os, sys
            from pathlib import Path
            rec = json.load(sys.stdin)
            keys = ("LOOKOUT_FARM", "LOOKOUT_WATCH", "LOOKOUT_STATE", "LOOKOUT_SINCE", "LOOKOUT_DRY_RUN")
            out = {k: os.environ.get(k) for k in keys}
            out.update(cwd=os.getcwd(), rec=rec["id"])
            Path(os.environ["LOOKOUT_STATE"], "seen.json").write_text(json.dumps(out))
        """
        record = self.record(body)
        seen = self.tmp / "w" / "check" / "seen.json"
        self.run_watch(record)
        first = json.loads(seen.read_text())
        self.assertEqual(first["LOOKOUT_SINCE"], "")
        self.assertEqual((first["LOOKOUT_FARM"], first["LOOKOUT_WATCH"], first["rec"]),
                         ("jobsearch", "replies", "replies"))
        self.assertIsNone(first["LOOKOUT_DRY_RUN"])
        self.assertEqual(Path(first["cwd"]).resolve(), self.farm.resolve())
        self.assertEqual(Path(first["LOOKOUT_STATE"]).resolve(), (self.tmp / "w" / "check").resolve())
        self.run_watch(record, now=NOW + dt.timedelta(minutes=5))
        self.assertEqual(json.loads(seen.read_text())["LOOKOUT_SINCE"], "2026-10-14T09:00:00+00:00")
        self.run_watch(record, dry_run=True)
        self.assertEqual(json.loads(seen.read_text())["LOOKOUT_DRY_RUN"], "1")

    def test_argv_expansion(self):
        words = runner.argv("{python} {checks}/email.py --query 'a b' ~/x", python="/py", checks="/c")
        self.assertEqual(words, ["/py", "/c/email.py", "--query", "a b", os.path.expanduser("~/x")])
        self.assertEqual(runner.argv("{python} x")[0], sys.executable)

    def test_timeout_is_broken(self):
        record = self.record("import time\ntime.sleep(30)\n", timeout=1)
        self.assertEqual(runner.timeout(record), 1)
        with mock.patch.object(runner, "timeout", lambda record: 0.3):  # below the record's floor of 1 s
            result = self.run_watch(record)
        self.assertEqual((result["outcome"], result["record"]["state"]), ("broken", "broken"))
        self.assertEqual(paths.read_log(self.log)[-1]["detail"], "timeout")

    def test_broken_outputs(self):
        cases = (("import sys\nsys.stderr.write('boom')\nsys.exit(3)\n", "exit 3"),
                 ("import sys\nprint('not json')\nsys.exit(10)\n", "found line is not JSON"),
                 ("import sys\nprint('{\"id\": \"x\"}')\nsys.exit(10)\n", "found line without id or summary"),
                 ("import sys\nsys.exit(10)\n", "found without an event"),
                 ("import sys\nprint('x' * 70000)\n", "stdout over 64 kB"))
        for body, detail in cases:
            result = self.run_watch(self.record(body))
            self.assertEqual(result["outcome"], "broken", body)
            self.assertEqual(result["record"]["last_result"], detail)
        self.assertEqual(paths.read_log(self.log)[0]["stderr"], "boom")

    def test_missing_program_is_broken(self):
        record = dict(self.record("pass\n"), check="/no/such/check")
        self.assertEqual(self.run_watch(record)["outcome"], "broken")

    def test_unreachable_cause(self):
        body = "import sys\nprint('{\"cause\": \"offline\", \"detail\": \"no network\"}')\nsys.exit(75)\n"
        result = self.run_watch(self.record(body))
        self.assertEqual(result["outcome"], "unreachable")
        self.assertEqual(result["record"], {"last_run": NOW.isoformat(), "last_result": "offline: no network",
                                            "state": "unreachable"})
        self.assertIsNone(result["alert"])
        result = self.run_watch(self.record("import sys\nprint('plain')\nsys.exit(75)\n"))
        self.assertEqual(result["record"]["last_result"], "unknown: plain")


class FindAndJudgeTest(Base):
    def test_found_with_judge_dedupes_and_judges_each_new_event_once(self):
        record = self.record(FOUND % 10, judge="Classify.")
        result = self.run_watch(record)
        self.assertEqual((result["outcome"], result["new"], result["end"]), ("found", 2, False))
        self.assertEqual([f["event"]["id"] for f in result["finds"]], ["email-1", "email-2"])
        self.assertTrue(all(f["judged"] and f["title"] == "Acme: invitation" for f in result["finds"]))
        self.assertEqual(len(self.claude_calls()), 2)
        state = watchstate.load(self.tmp / "w")
        for event_id in ("email-1", "email-2"):
            watchstate.deliver(state, event_id, NOW)
        watchstate.save(self.tmp / "w", state)
        again = self.run_watch(record, now=NOW + dt.timedelta(minutes=5))
        self.assertEqual((again["new"], again["finds"]), (0, []))
        self.assertEqual(len(self.claude_calls()), 2)
        self.assertEqual(len([l for l in paths.read_log(self.log) if l["kind"] == "judge"]), 2)

    def test_found_without_judge_runs_no_model(self):
        result = self.run_watch(self.record(FOUND % 10))
        self.assertEqual([(f["judged"], f["title"]) for f in result["finds"]],
                         [(False, "mail 1"), (False, "mail 2")])
        self.assertEqual(self.claude_calls(), [])

    def test_settled_ends_the_watch(self):
        result = self.run_watch(self.record(FOUND % 11))
        self.assertTrue(result["end"])
        self.assertEqual(result["record"]["state"], "found")

    def test_ignore_is_delivered_without_a_find(self):
        fakes.set_result(self.tmp / "bin", dict(fakes.SUCCESS, structured_output={
            "verdict": "ignore", "title": "spam", "notify": "spam"}))
        result = self.run_watch(self.record(FOUND % 10, judge="Classify."))
        self.assertEqual(result["finds"], [])
        self.assertEqual(sorted(watchstate.load(self.tmp / "w")["delivered"]), ["email-1", "email-2"])

    def test_three_judge_failures_go_on_unjudged(self):
        fakes.set_result(self.tmp / "bin", "not json")
        record = self.record(FOUND % 10, judge="Classify.")
        for minute, pending in ((0, 2), (5, 2), (10, 0)):
            result = self.run_watch(record, now=NOW + dt.timedelta(minutes=minute))
            state = watchstate.load(self.tmp / "w")
            self.assertEqual(len([p for p in state["pending"] if p["step"] == "judge"]), pending)
        self.assertEqual([(f["judged"], f["title"]) for f in result["finds"]], [(False, "mail 1"), (False, "mail 2")])
        self.assertEqual(len(self.claude_calls()), 6)

    def test_daily_cap_goes_on_unjudged_at_once(self):
        (self.tmp / "cfg").mkdir()
        (self.tmp / "cfg" / "settings.json").write_text('{"daily_budget_usd": 0}')
        result = self.run_watch(self.record(FOUND % 10, judge="Classify."))
        self.assertEqual([f["judged"] for f in result["finds"]], [False, False])
        self.assertEqual(self.claude_calls(), [])

    def test_dry_run_judges_nothing_and_saves_nothing(self):
        result = self.run_watch(self.record(FOUND % 10, judge="Classify."), dry_run=True)
        self.assertEqual(len(result["finds"]), 2)
        self.assertEqual(self.claude_calls(), [])
        self.assertFalse((self.tmp / "w" / "state.json").exists())


class AlertTest(unittest.TestCase):
    def test_three_broken_in_a_row_alert_once_until_a_clean_run(self):
        state = watchstate.empty()
        alerts = [watchstate.account(state, "broken", None, NOW, "Replies", NOW) for _ in range(4)]
        self.assertEqual([a is not None for a in alerts], [False, False, True, False])
        self.assertIn("Watch Replies not checkable since", alerts[2]["message"])
        watchstate.account(state, "quiet", None, NOW, "Replies", NOW)
        self.assertEqual((state["failures"], state["alerted"]), (0, {}))
        self.assertEqual(state["since"], "2026-10-14T09:00:00+00:00")

    def test_unreachable_alerts_after_six_hours_auth_at_once(self):
        state = watchstate.empty()
        self.assertIsNone(watchstate.account(state, "unreachable", "offline", NOW, "R", NOW))
        late = NOW + dt.timedelta(hours=6)
        self.assertEqual(watchstate.account(state, "unreachable", "offline", late, "R", late)["cause"], "offline")
        self.assertIsNone(watchstate.account(state, "unreachable", "offline", late, "R", late))
        fresh = watchstate.empty()
        self.assertEqual(watchstate.account(fresh, "unreachable", "auth", NOW, "R", NOW)["cause"], "auth")

    def test_prune_keeps_thirty_days(self):
        state = watchstate.empty()
        state["delivered"] = {"old": (NOW - dt.timedelta(days=31)).isoformat(), "new": NOW.isoformat()}
        watchstate.prune(state, NOW)
        self.assertEqual(list(state["delivered"]), ["new"])


if __name__ == "__main__":
    unittest.main()


class ProcReviewTest(unittest.TestCase):
    def test_a_timeout_does_not_wait_for_a_grandchild_that_left_the_group(self):
        import sys
        import time
        import proc
        code = ("import subprocess,sys;subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],"
                "start_new_session=True);import time;time.sleep(30)")
        self.assertEqual(proc.DRAIN, 5)
        start = time.monotonic()
        with mock.patch.object(proc, "DRAIN", 0.2):  # the drain's length is not the point: that it ends is
            run = proc.run([sys.executable, "-c", code], cwd=None, env=None, timeout=1)
        self.assertTrue(run["timed_out"])
        self.assertLess(time.monotonic() - start, 12)
