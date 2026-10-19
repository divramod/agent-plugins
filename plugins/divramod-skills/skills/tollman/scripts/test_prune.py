"""The prune duty (prune.py; hal2 plan 0377 step 7, D12): the tollman asks /prune's CLI (a fake here: a stub script that
prints a canned `plan --json`) and keeps its triggers, a muck out per landing, one removal per round, the 6-hourly disk
report, and starts one detached run. No real /prune, hal2-cli-runs, session or removal."""

import contextlib
import datetime as dt
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import prune
import tick

NOW = dt.datetime(2026, 10, 18, 10, 0, tzinfo=dt.timezone.utc)
STUB = '''import json, sys
from pathlib import Path
here = Path(__file__).parent
(here / "argv.json").write_text(json.dumps(sys.argv[1:]))
out = (here / "plan.json").read_text()
if out.startswith("exit "):
    print("boom", file=sys.stderr); sys.exit(int(out[5:]))
print(out)
'''
GB = 10 ** 9


def field(slot, free=True, size=0, sessions=(), head=None):
    return {"slot": slot, "path": f"/x/{slot}", "head": head or f"h{slot}", "proof": None if free else "uncommitted",
            "sessions": list(sessions), "size": {"bytes": size, "lower_bound": False}}


def todo(slot, action, **more):
    return {"field": slot, "action": action, "why": "free by the proof", "bytes": 0, "lower_bound": False, **more}


def data(fields, free_gb=400.0, **jobs):
    empty = {"skipped": "nothing", "actions": []}
    return {"plan": {"jobs": {n: {**empty, **jobs.get(n, {})} for n in ("stale-pointers", "phase-1", "phase-2", "phase-3")}},
            "facts": {"disk": {"free_gb": free_gb, "used_pct": 50.0, "total_gb": 1000.0}, "fields": fields}}


class Fake(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.stub = self.tmp / "stub" / "prune.py"
        self.stub.parent.mkdir()
        self.stub.write_text(STUB)
        (self.tmp / "state").mkdir()
        for stream in (contextlib.redirect_stdout, contextlib.redirect_stderr):  # start and main print; keep the run quiet
            quiet = stream(io.StringIO())
            quiet.__enter__()
            self.addCleanup(quiet.__exit__, None, None, None)
        self.main = str(self.tmp / "hal2")
        Path(self.main).mkdir()
        for patch in (mock.patch.object(prune, "script", return_value=self.stub),
                      mock.patch.object(prune, "state", return_value=self.tmp / "state"),
                      mock.patch.object(tick.mtm_scan, "DATA", self.tmp / "roles"),
                      mock.patch.object(prune.barn, "last_landed", return_value=None)):
            patch.start()
            self.addCleanup(patch.stop)

    def say(self, text):
        (self.stub.parent / "plan.json").write_text(text if isinstance(text, str) else json.dumps(text))

    def ctx(self, log=(), **more):
        return {"main": self.main, "top": "/x/tollman-hal2", "now": NOW, "log": list(log), **more}

    def round(self, d, log=(), **more):
        self.say(d)
        return tick.fresh(prune.plan({}, self.ctx(log, **more)), list(log), NOW)

    def kinds(self, actions):
        return [(a["kind"], a["do"], a["slot"]) for a in actions if a["kind"] not in ("disk", "low-disk")]


class Asking(Fake):
    def test_the_plan_is_asked_of_prunes_cli_as_a_program(self):
        self.say(data([]))
        got, why = prune.ask(self.main)
        self.assertEqual((got["facts"]["disk"]["free_gb"], why), (400.0, ""))
        self.assertEqual(json.loads((self.stub.parent / "argv.json").read_text()), ["plan", "--json", "--cached-sizes", "--repo", self.main])

    def test_a_failing_missing_or_garbled_prune_is_a_wake_once_per_6_hours(self):
        self.say("exit 2")
        got, why = prune.ask(self.main)
        self.assertIsNone(got)
        self.assertIn("exited 2: boom", why)
        self.assertEqual([(a["kind"], a["do"]) for a in self.round("exit 1")], [("failed", "wake")])
        self.say("not json")
        self.assertIn("gave no plan", prune.ask(self.main)[1])
        with mock.patch.object(prune, "script", side_effect=FileNotFoundError("skill 'prune' not found")):
            self.assertIn("not found", prune.ask(self.main)[1])
        wake = prune.plan({}, self.ctx())[0]
        later = [{"at": (NOW - dt.timedelta(hours=1)).isoformat(), "key": wake["key"]}]
        self.assertEqual(self.round("exit 1", later), [])


class Planning(Fake):
    def test_a_free_keeper_is_mucked_out_once_per_landing_a_free_field_removed_one_per_round(self):
        d = data([field("03"), field("13"), field("14")], **{"phase-1": {"actions": [
            todo("14", "remove"), todo("03", "muck-out"), todo("13", "remove")]}})
        actions = self.round(d)
        self.assertEqual(self.kinds(actions), [("remove", "run", "14"), ("clean", "record", "03")],
                         "one removal: the first of /prune's order (the cars come first there)")
        self.assertEqual([a["key"] for a in actions[:2]], ["prune:remove:14:h14", "prune:clean:03:h03"])
        run = actions[0]
        self.assertEqual(run["argv"][1:], [str(Path(prune.__file__).resolve()), "start", "--repo", self.main, "--slot",
                                          "tollman-hal2", "--field", "03", "--field", "14"])
        self.assertEqual(run["cwd"], self.main)
        log = [{"at": NOW.isoformat(), "key": a["key"]} for a in actions]
        self.assertEqual(self.kinds(self.round(d, log)), [("remove", "run", "13")], "the landing's HEAD cleaned once")
        moved = data([field("03", head="new")], **{"phase-1": {"actions": [todo("03", "muck-out")]}})
        self.assertEqual(self.kinds(self.round(moved, log)), [("clean", "run", "03")], "a new landing, a new muck out")

    def test_a_stale_pointer_and_the_trims_are_started_the_asks_are_not(self):
        d = data([field("13"), field("04", False), field("05", False), field("31", False)], **{
            "stale-pointers": {"actions": [todo("13", "clear-pointer", plan="0306-x")]},
            "phase-1": {"actions": [todo("31", "ask", foreman="02")]},
            "phase-2": {"actions": [todo("04", "trim", paths=["code/rust/target"])]},
            "phase-3": {"actions": [todo("05", "trim", paths=["code/rust/target"])]}})
        actions = self.round(d)
        self.assertEqual(self.kinds(actions), [("pointer", "run", "13"), ("trim", "record", "04"), ("trim", "record", "05")])
        self.assertEqual([a["key"] for a in actions[:3]],
                         ["prune:pointer:13:0306-x", "prune:trim:04:h04", "prune:trim:05:h05"])
        self.assertEqual(actions[0]["argv"][-6:], ["--field", "04", "--field", "05", "--field", "13"])

    def test_nothing_planned_nothing_started(self):
        self.assertEqual(self.kinds(self.round(data([field("13", False)]))), [])

    def test_a_run_that_still_lives_plans_nothing_a_dead_one_does_not_hold(self):
        d = data([field("13")], **{"phase-1": {"actions": [todo("13", "remove")]}})
        pid_file = self.tmp / "state" / prune.RUN_FILE
        pid_file.write_text(json.dumps({"pid": 77, "at": time.time()}))
        with mock.patch.object(prune, "alive", return_value=True):
            self.assertEqual(self.round(d), [])
            pid_file.write_text(json.dumps({"pid": 77, "at": 0.0}))  # alive but 1970: a reused pid
            self.assertEqual(self.kinds(self.round(d)), [("remove", "run", "13")])
        pid_file.write_text(json.dumps({"pid": 77, "at": time.time()}))
        with mock.patch.object(prune, "alive", return_value=False):
            self.assertEqual(self.kinds(self.round(d)), [("remove", "run", "13")])

    def test_the_planned_run_is_executed_by_the_tick_and_a_failed_start_wakes(self):
        d = data([field("13")], **{"phase-1": {"actions": [todo("13", "remove")]}})
        run = self.round(d)[0]
        for code, wakes in ((0, []), (1, ["failed"])):
            out = {}
            with mock.patch.object(tick, "sh", return_value=(code, "x")) as sh:
                tick.execute(dict(run), "/x/tollman-hal2", self.main, out)
            self.assertEqual(sh.call_args.args[0][2], "start")
            self.assertEqual([a["kind"] for a in out.get("wake", [])], wakes)


class Starting(Fake):
    def test_the_run_is_detached_under_hal2_cli_runs_exec(self):
        spawned = mock.Mock(pid=4242)
        popen = mock.Mock(return_value=spawned)
        with mock.patch.object(prune.shutil, "which", return_value="/usr/bin/hal2-cli-runs"), \
                mock.patch.object(prune, "alive", return_value=False):
            self.assertEqual(prune.start(self.main, "tollman-hal2", ["03", "14"], popen), 0)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[:8], ["hal2-cli-runs", "exec", "--workflow", "prune", "--slot", "tollman-hal2", "--trigger",
                                    "the tollman's duty prune"])
        self.assertEqual(argv[9:], [sys.executable, str(self.stub), "run", "--repo", self.main, "--field", "03", "--field", "14"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(popen.call_args.kwargs["cwd"], self.main)
        self.assertEqual(json.loads((self.tmp / "state" / prune.RUN_FILE).read_text())["pid"], 4242)

    def test_without_hal2_cli_runs_prune_runs_alone_and_only_one_at_a_time(self):
        popen = mock.Mock(return_value=mock.Mock(pid=os.getpid()))
        with mock.patch.object(prune.shutil, "which", return_value=None):
            prune.start(self.main, "tollman-hal2", [], popen)
            self.assertEqual(popen.call_args.args[0], [sys.executable, str(self.stub), "run", "--repo", self.main])
            popen.reset_mock()
            prune.start(self.main, "tollman-hal2", [], popen)  # the first still lives (this test's pid)
        popen.assert_not_called()

    def test_the_cli_starts_and_shows_the_plan_through_prunes_script(self):
        self.say(data([]))
        with mock.patch.object(prune.mtm_scan, "main_checkout", return_value=self.main), \
                mock.patch.object(subprocess, "call", return_value=0) as call:
            self.assertEqual(prune.main(["plan", "--json", "--repo", self.main]), 0)
        self.assertEqual(call.call_args.args[0], [sys.executable, str(self.stub), "plan", "--repo", self.main, "--json"])
        with mock.patch.object(prune, "script", side_effect=FileNotFoundError("x")), \
                mock.patch.object(prune.mtm_scan, "main_checkout", return_value=self.main):
            self.assertEqual(prune.main(["start", "--repo", self.main]), 2)


class Report(Fake):
    def test_disk_is_reported_every_6_hours_from_prunes_facts_a_notice_under_100_gb(self):
        fs = [field("03", size=12 * GB), field("13", size=3 * GB), field("14")]
        disk = [a for a in self.round(data(fs)) if a["kind"] in ("disk", "low-disk")]
        self.assertEqual([a["do"] for a in disk], ["record"])
        self.assertIn("free disk 400 GB; biggest worktrees: 03 12 GB, 13 3 GB", disk[0]["text"])
        low = [a["kind"] for a in self.round(data(fs, free_gb=80.0))]
        self.assertIn("low-disk", low)
        later = [{"at": (NOW - dt.timedelta(hours=1)).isoformat(), "key": "prune:disk:2026-10-18T09"}]
        self.assertEqual([a for a in prune.plan({}, self.ctx(later), data(fs)) if a["kind"] == "disk"], [])


if __name__ == "__main__":
    unittest.main()
