"""Hal2 plan 0349 step 28 (D75): the pretest's processes (pretest_jobs.py) with the stub gate (pretest_stub.py):
parallel and group bounds, the budget, every red named at once (plan 0522 D14), how a job's end is judged, and that
no process outlives the pretest (a timeout of a gate call, an exception or SIGTERM in the middle of the jobs)."""

import os
import subprocess
import time
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import pretest
import pretest_jobs
import stall_fake
from pretest_stub import EventClock, FieldCase, config, gone, meet


class Jobs(FieldCase):
    def test_the_budget_cuts_a_job_and_that_is_incomplete_never_passed(self):
        # plan 0522 D7 gap: a cut job counted as skipped and the push went (records-check cut at 168 s, 2026-10-25/26)
        self.stub.job("python-lint", "sleep 300")
        # The budget ends once python-lint runs (its pid file), however slow the machine was before.
        clock = EventClock(lambda: (self.stub.dir / "pid-python-lint").exists())
        with mock.patch.object(pretest, "time", clock), mock.patch.object(pretest_jobs, "time", clock):
            r = self.run_it(["python-lint", "bash-lint"], budget=300, parallel=1)
        self.assertNotIn("python-lint", self.stub.finished(), "the sleeping job was killed")
        self.assertEqual((r["result"], self.states(r)),
                         ("incomplete", [("python-lint", "skipped", None), ("bash-lint", "skipped", None)]))
        self.assertEqual([j["why"] for j in r["jobs"]],
                         ["the budget ended while it ran", "the budget ended before it started"])
        self.assertIn("the budget cut python-lint, bash-lint: not green, the push waits", r["why"])
        self.assertEqual(self.marked(), [])

    def test_a_red_stops_no_other_job_and_every_red_is_named_with_its_line(self):
        # plan 0522 D14: the first red stopped the rest, so a train met its second local red only at the next pretest
        self.stub.job("python-lint", "echo ok; echo 'x.py:3:1: E501 line too long'; code=1")
        self.stub.job("bash-lint", "sleep 0.3")
        self.stub.job("records-check", "echo 'error: record x has no rule'; code=1")
        r = self.run_it(["bash-lint", "python-lint", "records-check"], parallel=2)
        self.assertEqual((r["result"], self.states(r)),
                         ("red", [("bash-lint", "run", "green"), ("python-lint", "run", "red"),
                                  ("records-check", "run", "red")]))
        self.assertEqual([j["why"] for j in r["jobs"]], ["", "exit 1", "exit 1"])
        self.assertEqual(r["errors"], {"python-lint": "x.py:3:1: E501 line too long",
                                       "records-check": "error: record x has no rule"})
        self.assertIn("records-check", self.stub.ran(), "started after the red")
        self.assertEqual(self.marked(), ["gate-bash-lint-k-bash-lint"], "a red is never cached; the green beside it is")
        self.assertIn("E501", self.log.read_text())

    def test_a_red_with_a_job_the_budget_cut_is_red_and_says_what_is_not_known(self):
        self.stub.job("python-lint", "code=1")
        self.stub.job("bash-lint", "sleep 30")
        r = self.run_it(["python-lint", "bash-lint"], budget=1.5, parallel=2)
        self.assertEqual((r["result"], r["why"]), ("red", "the budget cut bash-lint: not known"))

    def test_the_first_error_line_reads_the_output(self):
        self.assertEqual(pretest.first_error("compiling\nwarning: x\n  FAILED test_a\nmore\n"), "FAILED test_a")
        self.assertEqual(pretest.first_error("gate: unit a: failed 1 s\nlast words\n"), "last words")
        self.assertEqual(pretest.first_error(""), "no output")

    def test_jobs_that_end_in_the_same_poll_are_each_judged(self):
        self.stub.job("python-lint", "code=1")
        with mock.patch.object(pretest_jobs, "POLL", 1.0):  # both end before the first look
            r = self.run_it(["bash-lint", "python-lint"], parallel=2)
        self.assertEqual(self.states(r), [("bash-lint", "run", "green"), ("python-lint", "run", "red")])

    def test_only_the_gates_tool_marker_or_an_outside_signal_is_skipped_every_other_failure_is_red(self):
        self.stub.job("python-lint", "echo 'gate: tool missing: buf' >&2; code=1")
        self.stub.job("bash-lint", "kill -KILL $$")
        r = self.run_it(["python-lint", "bash-lint"])
        self.assertEqual((r["result"], self.states(r)),
                         ("skipped", [("python-lint", "skipped", None), ("bash-lint", "skipped", None)]))
        self.assertEqual([j["why"] for j in r["jobs"]],
                         ["gate: tool missing: buf", "killed by signal 9 from outside"])
        for code in ("127", "126"):
            self.stub.job("python-lint", f"echo 'ruff: command not found'; code={code}")
            r = self.run_it(["python-lint"])
            self.assertEqual((r["result"], r["jobs"][0]["why"]), ("red", f"exit {code}"))

    def test_parallel_is_a_bound(self):
        jobs = ["python-lint", "bash-lint", "records-check", "lua-lint"]
        for j in jobs:  # two at once meet: the bound is reached however slow a start (plan 0532 step 16)
            self.stub.job(j, meet(2))
        r = self.run_it(jobs, parallel=2)
        self.assertEqual(r["result"], "green")
        counts = [int(c) for c in (self.stub.dir / "counts").read_text().split()]
        self.assertEqual((len(counts), max(counts)), (4, 2))

    def test_the_jobs_of_one_group_never_overlap(self):
        jobs = ["python-lint", "bash-lint", "records-check", "lua-lint"]
        for j in jobs:  # the three free to run meet: they overlap however slow a start (plan 0532 step 16)
            wait = ":" if j == "bash-lint" else meet(3)
            self.stub.job(j, f"echo {j} >>\"$here/order\"; {wait}; echo end-{j} >>\"$here/order\"")
        r = self.run_it(jobs, parallel=3, groups={"python-lint": "ts", "bash-lint": "ts"})
        self.assertEqual(r["result"], "green")
        order = (self.stub.dir / "order").read_text().split()
        # The starts as the stub logs them first thing (`calls`): a job's own echo into `order` may come after the next
        # job's start once the meet has let its partners end.
        starts = [c.split()[1] for c in (self.stub.dir / "calls").read_text().splitlines() if c.startswith("run ")]
        self.assertEqual(starts[-1], "bash-lint", "the group's second job waits; the free ones start before it")
        self.assertLess(order.index("end-python-lint"), order.index("bash-lint"), "never side by side")
        counts = [int(c) for c in (self.stub.dir / "counts").read_text().split()]
        self.assertEqual(max(counts), 3)
        cfg = config(self.tmp / "g.toml", jobs, groups={"python-lint": "ts", "bash-lint": "ts"})
        self.assertEqual(pretest.read_config(cfg)[0]["groups"], {"python-lint": "ts", "bash-lint": "ts"})

    def test_whatever_ends_the_pretest_stops_its_jobs(self):
        self.stub.job("python-lint", 'sleep 300 & echo $! >"$here/child-python-lint"; wait')
        real, told = time.sleep, []

        def interrupted(seconds):  # the landing's process is told to stop while the job runs (SIGTERM: SystemExit)
            if not told and (self.stub.dir / "child-python-lint").exists():
                told.append(1)  # once: time.sleep is also what Popen.wait sleeps with while stop() waits
                raise SystemExit(143)
            real(seconds)

        with mock.patch.object(pretest_jobs.time, "sleep", interrupted), self.assertRaises(SystemExit):
            self.run_it(["python-lint"])
        for name in ("pid-python-lint", "child-python-lint"):
            self.assertTrue(gone(int((self.stub.dir / name).read_text())), f"{name} outlived the pretest")

    def test_a_gate_call_past_its_timeout_takes_its_children_with_it(self):
        (self.stub.dir / "plan-hangs").touch()
        # The 1 s limit starts once the plan hangs (its child started, a line in $READY): a slow start is no early
        # timeout (the farmer's stall_fake, plan 0532 step 16).
        env = stall_fake.install(self, self.tmp)
        stall_fake.Ready.stalls.add(self.stub.main.name)
        with mock.patch.dict(os.environ, {"READY": env["READY"]}), self.assertRaises(subprocess.TimeoutExpired):
            pretest.plan(str(self.top), self.stub.main, "HEAD~1", "HEAD", 1.0)
        stall_fake.Ready.stalls.clear()
        self.assertFalse((self.stub.dir / "plan-finished").exists(), "the limit cut the plan, not its 300 s")
        self.assertTrue(gone(int((self.stub.dir / "plan-child").read_text())), "the plan's child built on")
        with mock.patch.object(pretest, "GATE_SECONDS", 1.5):
            r = self.run_it(["python-lint"])
        self.assertEqual(r["result"], "incomplete", "not green: the push waits (plan 0522 D7)")
        self.assertIn("the gate did not answer", r["why"])


if __name__ == "__main__":
    unittest.main()
