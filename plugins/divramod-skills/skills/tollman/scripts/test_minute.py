"""Hal2 plan 0383 step 4 (D4): the tollman's 1-minute duty `watch`. A minute on which only the watch is due is a pass,
not a round: a quiet one prints nothing, each event of the live land run (a job failed, the merge job green, the workflow
finished) prints one line, once. Whole ticks on test_tollman's farm; gh is gh_fake.py's, the queue is data."""
# enforces .adr/deterministic-first.md and .adr/tollman.md

import datetime as dt
import fcntl
import json
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import due
import leavers
import minute
import mtm_scan
import role_cli
import tick
import train_state
import tollman
import watch_events
from gh_fake import FakeGh, job, run
from test_tollman import Field

ROLE = """---
duties:
  mtm: "*/15 * * * *"
  trains: "*/15 * * * *"
  watch: "* * * * *"
notify: every-round
---

# the tollman
"""
NAME = "07+09@2026-10-17T10:00:00Z"
BRANCH = "train-0383-0365"
CARS = [{"field": "07", "branch": "07", "head": "7" * 40, "plan": "0383-train-rules"},
        {"field": "09", "branch": "09", "head": "9" * 40, "plan": "0365-x"}]
RUN = run(501, "land/" + BRANCH, "2099-01-01T00:00:00Z", status="in_progress")
LOG = "d1-01-rust-test\ttest\t2026-10-17T10:08:00.1Z test hub::tenant_rls ... FAILED\nd1-01-rust-test\ttest\tmore"
URL = RUN["url"]


class Pass(Field):
    def setUp(self):
        super().setUp()
        self.commit(self.wm, tollman.WIRING.role_file, ROLE)  # the field's own role file: only it may differ
        self.wm_state.mkdir(parents=True, exist_ok=True)
        for item in ("duty:mtm", "duty:trains"):  # just ran: only the watch is due
            due.record_run(str(self.wm), item, role="tollman")
        self.gh = FakeGh([RUN], jobs={"501": [job("d1-01-rust-test", None)]}, logs={"501": LOG}).start(self)
        self.sh = []
        real = tick.sh

        def sh(argv, cwd, timeout=900):  # hal2-cli-git is a fake that never runs (test_silent_trains)
            self.sh.append(argv)
            return (0, json.dumps({"status": "ok"})) if argv[0] == "hal2-cli-git" else real(argv, cwd, timeout)

        for p in (mock.patch.object(tick, "sh", sh),
                  mock.patch.object(tick.deliver, "cli", lambda *a: (0, "[]"))):
            p.start()
            self.addCleanup(p.stop)
        self.call("mode", "timer")

    def train(self, *kinds):
        for kind in kinds:
            extra = {"cars": CARS, "base": "b" * 40} if kind == "formed" else {"pid": 4711, "land_ref": BRANCH} \
                if kind == "started" else {}
            train_state.append(str(self.main), kind, "tollman-hal2", train=NAME, **extra)

    def tick(self):
        code, out = self.call("tick")
        self.assertEqual(code, 0)
        return out

    def set_run(self, jobs, **kw):
        self.gh.jobs["501"] = jobs
        self.gh.runs[:] = [dict(RUN, **kw)]


class Quiet(Pass):
    def test_the_role_file_with_the_watch_loops_every_minute(self):
        code, check = role_cli.start_check(str(self.wm), tollman.WIRING)
        self.assertEqual((code, check["loop_cron"]), (0, "* * * * *"))

    def test_a_quiet_minute_prints_nothing_and_runs_no_round(self):
        self.assertTrue(minute.light(str(self.wm), tollman.WIRING))
        self.assertEqual(self.tick(), "", "no train, no event: not a line")
        self.train("formed", "started")
        self.assertEqual(self.tick(), "", "a landing without news: not a line")
        self.assertEqual(self.sh, [], "no merge from main: a pass is no round")
        self.assertFalse((self.wm_state / "summaries").exists())
        self.assertEqual([c for c in self.gh.calls if c[1:3] == ["run", "view"]], [["gh", "run", "view", "501", "--json", "jobs"]])

    def test_a_round_is_due_when_more_than_the_watch_is(self):
        due.record_run(str(self.wm), "duty:mtm", dt.datetime(2020, 1, 1), role="tollman")
        self.assertFalse(minute.light(str(self.wm), tollman.WIRING))
        self.assertIn("tollman tick (round)", self.tick())

    def test_a_pass_needs_the_timer_mode_and_a_dry_run_is_a_round(self):
        self.call("mode", "claude")
        self.assertFalse(minute.light(str(self.wm), tollman.WIRING))
        self.call("mode", "timer")
        self.assertIn("tollman tick (dry run)", self.call("tick", "--dry-run")[1])

    def test_a_running_round_holds_the_pass_back_without_a_word(self):
        self.train("formed", "started")
        self.set_run([job("d1-01-rust-test", "failure")])
        with (self.wm_state / "tick.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.tick(), "")
        self.assertIn("job failed: d1-01-rust-test", self.tick(), "told once the round is done")


class Events(Pass):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(train_state, "alive", lambda pid: True)  # the landing's process runs (pid 4711)
        p.start()
        self.addCleanup(p.stop)

    def test_each_event_is_one_line_and_told_once(self):
        self.train("formed", "started")
        self.set_run([job("d1-01-rust-test", "failure"), job("d1-02-ts-test", None)])
        failed = "job failed: d1-01-rust-test: test hub::tenant_rls ... FAILED\n"
        self.assertEqual(self.tick(), failed)
        self.assertEqual(self.tick(), "", "the same job, the next minute: nothing")
        self.set_run([job("d1-01-rust-test", "failure"), job("d2-01-git-merge", "success")])
        self.assertEqual(self.tick(), f"merge job green: d2-01-git-merge ({URL})\n")
        self.assertEqual(self.tick(), "")
        self.set_run([job("d1-01-rust-test", "failure"), job("d2-01-git-merge", "success")], status="completed",
                     conclusion="failure")
        self.assertEqual(self.tick(), f"workflow finished: failure ({URL})\n")
        self.assertEqual(self.tick(), "")
        told = [e["key"] for e in self.wm_log() if e["duty"] == "watch"]
        self.assertEqual(told, ["job:501:d1-01-rust-test", "merge:501", "done:501"], "each in the round's log once")

    def test_several_new_events_are_several_lines_in_order(self):
        self.train("formed", "started")
        self.set_run([job("d1-01-rust-test", "failure"), job("d2-01-git-merge", "success")], status="completed",
                     conclusion="success")
        lines = self.tick().splitlines()
        self.assertEqual([x.split(":")[0].split(" (")[0] for x in lines],
                         ["job failed", "merge job green", "workflow finished"])
        self.assertTrue(all("\n" not in x for x in lines))

    def test_the_end_of_a_run_is_told_after_the_train_left_the_landing_state(self):
        self.train("formed", "started")
        self.set_run([job("d1-01-rust-test", None)])
        self.assertEqual(self.tick(), "")
        self.train("landed")  # the round marked it before the next minute
        self.set_run([job("d2-01-git-merge", "success")], status="completed", conclusion="success")
        self.assertEqual(self.tick().splitlines(), [f"merge job green: d2-01-git-merge ({URL})",
                                                    f"workflow finished: success ({URL})"])
        self.assertEqual(self.tick(), "", "a finished run is closed")

    def test_a_failed_job_without_a_log_names_its_failed_step(self):
        self.train("formed", "started")
        self.gh.logs.clear()
        self.set_run([job("d1-01-rust-test", "failure", step="cargo nextest")])
        self.assertEqual(self.tick(), "job failed: d1-01-rust-test: step cargo nextest failed\n")

    def test_a_new_start_watches_its_own_run(self):
        self.train("formed", "started")
        self.set_run([job("d1-01-rust-test", "failure")], status="completed", conclusion="failure")
        self.assertEqual(len(self.tick().splitlines()), 2)
        self.train("retry", "started")
        newer = run(502, "land/" + BRANCH, "2099-01-02T00:00:00Z", status="in_progress")
        self.gh.runs.insert(0, newer)
        self.gh.jobs["502"] = [job("d1-01-rust-test", "failure")]
        self.assertEqual(self.tick(), "job failed: d1-01-rust-test: step test failed\n",
                         "run 502 is a new run: its job is news")

    def test_the_round_s_function_returns_the_events_and_a_dry_look_tells_nothing(self):
        self.train("formed", "started")
        self.set_run([job("d1-01-rust-test", "failure")])
        main, rows = str(self.main), train_state.lines(str(self.main))
        first = watch_events.new(main, rows, dry=True)
        self.assertEqual([(e["kind"], e["key"]) for e in first], [("job-failed", "job:501:d1-01-rust-test")])
        self.assertEqual(watch_events.new(main, rows, dry=True), first, "a dry look marks nothing told")
        self.assertEqual(watch_events.new(main, rows), first)
        self.assertEqual(watch_events.new(main, rows), [])

    def test_a_full_round_plans_the_events_as_records_and_tells_them_in_its_silent_lines(self):
        self.train("formed", "started")
        self.set_run([job("d1-01-rust-test", "failure")])
        due.record_run(str(self.wm), "duty:mtm", dt.datetime(2020, 1, 1), role="tollman")
        planned = json.loads(self.call("tick", "--dry-run", "--json")[1])["planned"]
        self.assertIn(("watch", "job-failed", "record"),
                      [(a["duty"], a["kind"], a["do"]) for a in planned])
        handled = minute.handler({"name": "duty:watch"}, {"main": str(self.main), "dry": False})
        self.assertEqual([a["text"] for a in handled if a["do"] == "record"],
                         ["job failed: d1-01-rust-test: test hub::tenant_rls ... FAILED"])
        self.assertEqual([(a["kind"], a["do"], a["key"]) for a in handled if a["do"] != "record"],
                         [("train-red", "wake", "train-red:501")], "no file names a car: unclear, the session judges")
        lines = tollman.silent_lines(str(self.main), {"done": handled}, "9999-01-01T00:00:00Z")
        self.assertEqual(lines[0], handled[0]["text"])
        self.assertTrue(lines[1].startswith("| tollman | train "))


class Leavers(Pass):
    """The pass makes the round's leavers call (plan 0383 step 3) once, and does what it plans, keyed."""

    def setUp(self):
        super().setUp()
        self.told = [tick.act("trains", "queue-leaver", "record", "02", key="note:gone:02:7",
                              text="queue: 02 left the queue unmerged and is put back")]
        check = mock.patch.object(leavers, "check", return_value={"actions": self.told, "held": None})
        self.check = check.start()
        self.addCleanup(check.stop)

    def test_the_pass_calls_leavers_once_and_acts_once_without_a_word(self):
        self.assertEqual(self.tick(), "", "a leaver is no line of the watch")
        self.assertEqual(self.check.call_count, 1)
        self.assertEqual([e["key"] for e in self.wm_log()], ["note:gone:02:7"])
        self.assertEqual(self.tick(), "")
        self.assertEqual([e["key"] for e in self.wm_log()], ["note:gone:02:7"], "the key: told once")
        self.assertEqual(self.check.call_count, 2, "each pass looks")

    def test_the_agent_list_is_asked_only_when_a_message_is_typed(self):
        asked = mock.Mock(return_value={"panes": {"02": "%5"}})
        with mock.patch.object(tick, "context", asked):
            self.tick()
            self.assertEqual(asked.call_count, 0, "a quiet minute asks no agent")
            panes = minute.Panes(lambda: asked()["panes"])
            self.assertEqual((panes.get("02"), panes.get("09"), asked.call_count), ("%5", None, 1))

    def test_smuggle_mode_sleeps(self):
        with mock.patch.object(mtm_scan, "run_json", lambda args, cwd=None: {"queue": [], "mode": {"mode": "smuggle"}}):
            self.assertEqual(self.tick(), "")
        self.assertEqual(self.check.call_count, 0)


if __name__ == "__main__":
    unittest.main()
