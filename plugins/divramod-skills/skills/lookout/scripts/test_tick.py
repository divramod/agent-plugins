"""Tests of the tick (lookout_tick.py): a whole tick on a scratch store with fake checks, a fake `claude`, a fake
daybook command and a fake notifier. Never the real claude, a real notification or the real ~/.config."""

import contextlib
import datetime as dt
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import fakes
import find
import lookout
import lookout_tick
import paths
import store
import watchstate

T0 = dt.datetime(2026, 10, 14, 11, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
STEP = dt.timedelta(minutes=5)
DAYBOOK = """#!/usr/bin/env python3
import json, os, sys
with open(os.path.join(os.environ["FAKE_DIR"], "daybook.log"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
"""
APPLY = """#!/usr/bin/env python3
import os, sys
sys.exit(int(open(os.path.join(os.environ["FAKE_DIR"], "apply.exit")).read()))
"""
FOUND = """\
    import json, os, sys
    with open(os.path.join(os.environ["FAKE_DIR"], "runs.log"), "a") as f:
        f.write(os.environ["LOOKOUT_FARM"] + "/" + os.environ["LOOKOUT_WATCH"] + "\\n")
    print(json.dumps({"id": "email-1", "summary": "Acme: Ihre Bewerbung"}))
    sys.exit(%d)
"""
QUIET = FOUND.split("print(")[0] + "    print('nothing new')\n"
BROKEN = FOUND.split("print(")[0] + "    sys.stderr.write('boom')\n    sys.exit(3)\n"


class TickBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.claude_dir = self.tmp / "claude"
        claude = fakes.fake_claude(self.claude_dir)
        env = {"LOOKOUT_DIR": str(self.tmp / "cfg"), "LOOKOUT_STATE_DIR": str(self.tmp / "state"),
               "LOOKOUT_CLAUDE": claude, "FAKE_DIR": str(self.tmp), "LOOKOUT_BY": "tester"}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        self.daybook = self.script("daybook.py", DAYBOOK)
        self.script("apply.py", APPLY)
        (self.tmp / "apply.exit").write_text("0")
        self.sent = []
        self.farms = {}
        for name in ("alpha", "beta"):
            self.farms[name] = self.tmp / name
            self.farms[name].mkdir()
        (self.farms["alpha"] / "judge.md").write_text("Is this mail an invitation? Answer act or ignore.")

    def script(self, name, text):
        path = self.tmp / name
        path.write_text(text)
        return path

    def notifier(self, title, body, farm, watch, backends):
        self.sent.append((title, body, farm, watch, backends))
        return [{"backend": "fake", "ok": True, "error": None}]

    def add(self, farm, watch_id, body, **fields):
        check = fakes.fake_check(self.tmp, f"{farm}-{watch_id}", body)
        fields = dict({"title": watch_id.title(), "cron": "*/5 * * * *", "check": check}, **fields)
        name, path = store.farm_of(self.farms[farm])
        store.add(name, path, watch_id, fields, now=T0)

    def tick(self, n=0, **kw):
        ctx = lookout_tick.Ctx(now=T0 + n * STEP, daybook=str(self.daybook), notifier=self.notifier, settings={}, **kw)
        return lookout_tick.tick(ctx)

    def record(self, farm, watch_id):
        return next(w for w in store.load(farm)[1] if w["id"] == watch_id)

    def lines(self, name):
        path = self.tmp / name
        return path.read_text().splitlines() if path.exists() else []

    def runs(self):
        return self.lines("runs.log")

    def finds(self, farm):
        return find.read_finds(farm)


class QuietTickTest(TickBase):
    def test_a_quiet_tick_spends_nothing(self):
        self.add("alpha", "replies", QUIET, judge="@judge.md")
        self.add("beta", "page", QUIET)
        before = len(store.read_changes())
        out = self.tick()
        self.assertEqual(out, f"{T0.isoformat()} quiet (2 checked)")
        self.assertEqual(self.runs(), ["alpha/replies", "beta/page"])
        self.assertEqual(fakes.calls(self.claude_dir), [])  # no claude, no tokens
        self.assertEqual((self.lines("daybook.log"), self.sent, self.finds("alpha")), ([], [], []))
        record = self.record("alpha", "replies")
        self.assertEqual((record["state"], record["last_result"], record["last_run"]),
                         ("quiet", "nothing new", T0.isoformat()))
        self.assertEqual(len(store.read_changes()), before)  # run keys leave no change line (D10)
        self.assertEqual((paths.state_root() / "heartbeat").read_text().strip(), T0.isoformat())

    def test_a_watch_runs_only_when_its_cron_is_due(self):
        self.add("alpha", "hourly", QUIET, cron="0 * * * *")
        self.tick(0)
        self.tick(1)
        self.tick(2)
        self.assertEqual(len(self.runs()), 1)
        self.tick(12)  # 12:00
        self.assertEqual(len(self.runs()), 2)

    def test_an_ended_watch_and_a_prompt_only_watch_are_not_run(self):
        self.add("alpha", "old", QUIET)
        store.end("alpha", "old")
        name, path = store.farm_of(self.farms["alpha"])
        store.add(name, path, "daybook-only", {"title": "t", "cron": "* * * * *", "check": "true"})
        store.set_keys(name, "daybook-only", {"prompt": "look"})
        comments, watches = store.load(name)
        watches[-1].pop("check")  # a daybook prompt-only record
        store.save(name, comments, watches)
        self.assertEqual(self.tick(), f"{T0.isoformat()} quiet (0 checked)")
        self.assertEqual(self.runs(), [])

    def test_dry_run_plans_and_runs_nothing(self):
        self.add("alpha", "replies", QUIET)
        ctx = lookout_tick.Ctx(now=T0)
        self.assertEqual(lookout_tick.tick(ctx, dry_run=True), "would run alpha/replies")
        self.assertEqual(self.runs(), [])
        self.assertFalse((paths.state_root() / "heartbeat").exists())


class FindingTickTest(TickBase):
    def test_a_find_writes_record_daybook_item_and_one_notification_once(self):
        self.add("alpha", "replies", FOUND % 10, judge="@judge.md", notify="telegram")
        self.add("beta", "page", QUIET)
        out = self.tick(0)
        self.assertTrue(out.startswith(f"{T0.isoformat()} found 1 (2 checked); alpha/replies"), out)
        self.assertEqual(len(fakes.calls(self.claude_dir)), 1)  # one judge run
        [line] = self.finds("alpha")
        self.assertEqual((line["event"], line["judged"], line["title"], line["watch"]),
                         ("email-1", True, "Acme: invitation", "replies"))
        [call] = [json.loads(x) for x in self.lines("daybook.log")]
        self.assertEqual(call[0:3], ["--farm", str(self.farms["alpha"].resolve()), "jot"])
        self.assertEqual(call[3], "Acme: invitation [lookout:replies]")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0], ("Acme: invitation", "Acme: invitation", "alpha", "replies", ["telegram"]))
        record = self.record("alpha", "replies")
        self.assertEqual((record["state"], record["last_result"]), ("found", "Acme: invitation"))
        state = watchstate.load(paths.watch_dir("alpha", "replies"))
        self.assertIn("email-1", state["delivered"])
        self.assertEqual(state["pending"], [])
        # the check reports the same mail again: nothing repeats
        self.tick(1)
        self.tick(2)
        self.assertEqual(len(self.runs()), 3 * 2)
        self.assertEqual((len(fakes.calls(self.claude_dir)), len(self.finds("alpha")), len(self.sent),
                          len(self.lines("daybook.log"))), (1, 1, 1, 1))

    def test_a_find_without_judge_is_the_events_own_line_and_costs_no_tokens(self):
        self.add("beta", "page", FOUND % 10)
        self.tick()
        self.assertEqual(fakes.calls(self.claude_dir), [])
        [line] = self.finds("beta")
        self.assertEqual((line["judged"], line["title"]), (False, "Acme: Ihre Bewerbung"))
        self.assertEqual(len(self.sent), 1)

    def test_an_ignore_verdict_records_nothing(self):
        result = dict(fakes.SUCCESS, structured_output={"verdict": "ignore", "title": "spam", "notify": "spam"})
        fakes.set_result(self.claude_dir, result)
        self.add("alpha", "replies", FOUND % 10, judge="@judge.md")
        self.tick(0)
        self.tick(1)
        self.assertEqual((len(fakes.calls(self.claude_dir)), self.finds("alpha"), self.sent), (1, [], []))

    def test_a_failing_judge_is_retried_while_the_watch_is_not_due_then_the_find_goes_on_unjudged(self):
        fakes.set_result(self.claude_dir, "not json")
        self.add("alpha", "replies", FOUND % 10, judge="@judge.md", cron="0 * * * *")
        self.tick(0)
        self.assertEqual(self.finds("alpha"), [])
        self.assertEqual(self.record("alpha", "replies")["state"], "found")
        self.tick(1)  # not due: only the retry runs
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(len(fakes.calls(self.claude_dir)), 2)
        self.tick(2)
        [line] = self.finds("alpha")
        self.assertEqual((line["judged"], line["title"]), (False, "Acme: Ihre Bewerbung"))
        self.assertEqual(len(fakes.calls(self.claude_dir)), 3)
        self.tick(3)
        self.assertEqual((len(fakes.calls(self.claude_dir)), len(self.sent)), (3, 1))

    def test_a_failing_apply_keeps_the_find_pending_and_retries_without_doubling(self):
        (self.tmp / "apply.exit").write_text("1")
        self.add("alpha", "replies", FOUND % 10, apply=f"{{python}} {self.tmp / 'apply.py'}", cron="0 * * * *")
        self.tick(0)
        self.assertEqual((len(self.finds("alpha")), self.sent, self.record("alpha", "replies")["state"]),
                         (1, [], "pending"))
        self.tick(1)
        self.assertEqual(len(self.finds("alpha")), 1)  # the find line is written once
        (self.tmp / "apply.exit").write_text("0")
        self.tick(2)
        self.assertEqual((len(self.finds("alpha")), len(self.sent), len(self.lines("daybook.log"))), (1, 1, 1))
        self.assertEqual(self.record("alpha", "replies")["state"], "found")
        self.assertEqual(watchstate.load(paths.watch_dir("alpha", "replies"))["pending"], [])

    def test_a_failing_notifier_keeps_the_record_and_the_item(self):
        self.add("beta", "page", FOUND % 10)
        ctx = lookout_tick.Ctx(now=T0, daybook=str(self.daybook), settings={},
                               notifier=mock.Mock(side_effect=RuntimeError("down")))
        lookout_tick.tick(ctx)
        self.assertEqual((len(self.finds("beta")), len(self.lines("daybook.log"))), (1, 1))
        self.assertEqual(self.record("beta", "page")["state"], "found")

    def test_a_settled_check_ends_the_watch(self):
        self.add("beta", "page", FOUND % 11)
        self.assertIn("ended beta/page", self.tick())
        self.assertIs(self.record("beta", "page")["active"], False)
        line = store.read_changes("beta", "page")[-1]
        self.assertEqual((line["op"], line["by"]), ("end", "lookout tick"))
        self.tick(1)
        self.assertEqual(len(self.runs()), 1)


class AlertTest(TickBase):
    def test_a_broken_check_alerts_once_after_three_runs(self):
        self.add("beta", "page", BROKEN, title="The page")
        for n in range(2):
            self.tick(n)
        self.assertEqual((self.sent, self.record("beta", "page")["state"]), ([], "broken"))
        out = self.tick(2)
        self.assertIn("alert beta/page", out)
        [sent] = self.sent
        self.assertEqual(sent[0], "Watch The page")
        self.assertTrue(sent[1].startswith("Watch The page not checkable since "), sent[1])
        self.assertIn("[lookout:page]", json.loads(self.lines("daybook.log")[0])[3])
        self.tick(3)
        self.tick(4)
        self.assertEqual((len(self.sent), len(self.lines("daybook.log"))), (1, 1))
        self.assertEqual(len(self.runs()), 5)


class RobustTickTest(TickBase):
    def test_a_second_tick_is_busy_and_a_stale_lock_is_taken_over(self):
        self.add("beta", "page", QUIET)
        state = paths.state_root()
        state.mkdir(parents=True)
        (state / "tick.lock").write_text("")
        self.assertIn("busy", self.tick())
        self.assertEqual(self.runs(), [])
        old = time.time() - 700
        os.utime(state / "tick.lock", (old, old))
        self.assertIn("quiet", self.tick())
        self.assertFalse((state / "tick.lock").exists())  # released

    def test_a_broken_farm_file_does_not_stop_the_other_farms(self):
        self.add("beta", "page", QUIET)
        (paths.config_root() / "alpha.yaml").write_text("watches:\n- id: [x\n")
        out = self.tick()
        self.assertIn("unreadable alpha.yaml", out)
        self.assertEqual(self.runs(), ["beta/page"])

    def test_the_cli_tick_ignores_repo_and_run_dry_run_records_nothing(self):
        self.add("alpha", "replies", FOUND % 10, judge="@judge.md")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(lookout.main(["tick", "--repo", "/x", "--dry-run"]), 0)
        self.assertEqual(out.getvalue().strip(), "would run alpha/replies")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(lookout.main(["run", "replies", "--dry-run"]), 0)
        report = json.loads(out.getvalue())
        self.assertEqual((report["outcome"], report["new"], report["finds"]), ("found", 1, ["Acme: Ihre Bewerbung"]))
        self.assertEqual((fakes.calls(self.claude_dir), self.finds("alpha"), self.sent), ([], [], []))
        self.assertNotIn("state", self.record("alpha", "replies"))
        self.assertFalse((paths.watch_dir("alpha", "replies") / "state.json").exists())


if __name__ == "__main__":
    unittest.main()


class ReviewRegressionTest(TickBase):
    def test_an_unexpected_error_in_one_watch_does_not_stop_the_tick(self):
        self.add("alpha", "bad", QUIET)
        self.add("beta", "good", QUIET)
        real = lookout_tick.runner.run_watch

        def run_watch(record, *args, **kwargs):
            if record["id"] == "bad":
                raise TypeError("odd record")
            return real(record, *args, **kwargs)

        with mock.patch.object(lookout_tick.runner, "run_watch", run_watch):
            out = self.tick()
        self.assertIn("error alpha/bad: TypeError: odd record", out)
        self.assertEqual(self.runs(), ["beta/good"])
        self.assertEqual(self.record("beta", "good")["state"], "quiet")

    def test_a_record_with_odd_values_is_a_bad_cron_not_a_dead_tick(self):
        self.add("alpha", "odd", QUIET)
        self.add("beta", "good", QUIET)
        with mock.patch.object(lookout_tick.watchfile, "due", side_effect=[TypeError("x"), True]):
            out = self.tick()
        self.assertIn("bad cron alpha/odd", out)
        self.assertEqual(self.runs(), ["beta/good"])

    def test_the_judge_keeps_the_tick_lock_alive(self):
        beats = []
        ctx = lookout_tick.Ctx(now=T0, judge_fn=lambda *a, **k: {"ok": False, "reason": "x"}, settings={})
        self.add("alpha", "replies", FOUND % 10, judge="@judge.md")
        lookout_tick.run_tick(ctx, keepalive=lambda: beats.append(1))
        self.assertGreaterEqual(len(beats), 2)  # once for the watch, once more for the judge call
