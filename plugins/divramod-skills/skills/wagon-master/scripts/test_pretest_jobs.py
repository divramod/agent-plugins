"""Hal2 plan 0349 step 28 (D75): the pretest's processes (pretest_jobs.py) with the stub gate (pretest_stub.py):
parallel and group bounds, the budget, the first red, how a job's end is judged, and that no process outlives the
pretest (a timeout of a gate call, an exception or SIGTERM in the middle of the jobs)."""

import subprocess
import time
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import pretest
import pretest_jobs
from pretest_stub import FieldCase, config, gone


class Jobs(FieldCase):
    def test_the_budget_cuts_a_job_and_that_is_never_red(self):
        self.stub.job("python-lint", "sleep 30")
        began = time.monotonic()
        r = self.run_it(["python-lint", "bash-lint"], budget=1.5, parallel=1)
        self.assertLess(time.monotonic() - began, 10, "the sleeping job was killed")
        self.assertEqual((r["result"], self.states(r)),
                         ("skipped", [("python-lint", "skipped", None), ("bash-lint", "skipped", None)]))
        self.assertEqual([j["why"] for j in r["jobs"]],
                         ["the budget ended while it ran", "the budget ended before it started"])
        self.assertEqual(self.marked(), [])

    def test_the_first_red_stops_the_others(self):
        self.stub.job("python-lint", "echo boom; code=1")
        self.stub.job("bash-lint", "sleep 30")
        began = time.monotonic()
        r = self.run_it(["bash-lint", "python-lint", "records-check"], parallel=2)
        self.assertLess(time.monotonic() - began, 10)
        self.assertEqual((r["result"], self.states(r)),
                         ("red", [("bash-lint", "skipped", None), ("python-lint", "run", "red"),
                                  ("records-check", "skipped", None)]))
        self.assertEqual([j["why"] for j in r["jobs"]],
                         ["stopped: python-lint is red", "exit 1", "not started: python-lint is red"])
        self.assertNotIn("records-check", self.stub.ran())
        self.assertEqual(self.marked(), [], "a red is never cached")
        self.assertIn("boom", self.log.read_text())

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
        for j in jobs:
            self.stub.job(j, "sleep 0.4")
        r = self.run_it(jobs, parallel=2)
        self.assertEqual(r["result"], "green")
        counts = [int(c) for c in (self.stub.dir / "counts").read_text().split()]
        self.assertEqual((len(counts), max(counts)), (4, 2))

    def test_the_jobs_of_one_group_never_overlap(self):
        jobs = ["python-lint", "bash-lint", "records-check", "lua-lint"]
        for j in jobs:
            self.stub.job(j, f"echo {j} >>\"$here/order\"; sleep 0.4; echo end-{j} >>\"$here/order\"")
        r = self.run_it(jobs, parallel=3, groups={"python-lint": "ts", "bash-lint": "ts"})
        self.assertEqual(r["result"], "green")
        order = (self.stub.dir / "order").read_text().split()
        starts = [o for o in order if not o.startswith("end-")]
        self.assertEqual(starts[-1], "bash-lint", "the group's second job waits; the free ones start before it")
        self.assertLess(order.index("end-python-lint"), order.index("bash-lint"), "never side by side")
        counts = [int(c) for c in (self.stub.dir / "counts").read_text().split()]
        self.assertEqual(max(counts), 3)
        cfg = config(self.tmp / "g.toml", jobs, groups={"python-lint": "ts", "bash-lint": "ts"})
        self.assertEqual(pretest.read_config(cfg)[0]["groups"], {"python-lint": "ts", "bash-lint": "ts"})

    def test_whatever_ends_the_pretest_stops_its_jobs(self):
        self.stub.job("python-lint", 'sleep 30 & echo $! >"$here/child-python-lint"; wait')
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
        began = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            pretest.plan(str(self.top), self.stub.main, "HEAD~1", "HEAD", 1.0)
        self.assertLess(time.monotonic() - began, 10)
        self.assertTrue(gone(int((self.stub.dir / "plan-child").read_text())), "the plan's child built on")
        r = self.run_it(["python-lint"], budget=1.5)
        self.assertEqual(r["result"], "skipped")
        self.assertIn("the gate did not answer", r["why"])


if __name__ == "__main__":
    unittest.main()
