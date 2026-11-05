"""Plan 0623 step 4 (D6, L151): a state-scratch finding of files left under the real roots that no car's diff writes
is a runner red (retry, no car order). Replays train 32 attempt 5 (run 41144448386, hz01): claude `usage-ids.bin` and
`usage-index.json` left by another job of the shared runner user. A suite failure, an undeclared write of a test or a
path a car's files could write stays the car's."""

import unittest

import run_triage_check as check
import scratch_red
import triage
from gh_fake import job
from test_run_triage import one, unit

STRAY = ("hal2-cli-state: a test run left ~/.claude/usage-ids.bin under the real roots, which no declared store covers\n"
         "hal2-cli-state: a test run left ~/.claude/usage-index.json under the real roots, which no declared store covers")
CARS = [{"field": "02", "files": ["code/rust/libs/x/src/lib.rs"]}, {"field": "09", "files": ["docs/y.md"]}]
WRITER = [{"field": "05", "files": ["code/rust/libs/hal2-usage/src/usage_ids.rs"]}]


class Reads(unittest.TestCase):
    def test_the_recorded_lines(self):
        self.assertEqual(scratch_red.read(STRAY)["paths"], [".claude/usage-ids.bin", ".claude/usage-index.json"])

    def test_a_suite_failure_or_an_own_write_is_not_a_stray(self):
        self.assertIsNone(scratch_red.read(STRAY + "\nhal2-cli-state: a suite failed: rust-test"))
        self.assertIsNone(scratch_red.read(STRAY + "\nwrote ~/.x/a.json, which no declared store covers"))
        self.assertIsNone(scratch_red.read("boom"))

    def test_a_car_writing_the_store_keeps_the_red(self):
        found = scratch_red.read(STRAY)
        self.assertIsNotNone(scratch_red.runner(found, CARS))
        self.assertIsNone(scratch_red.runner(found, CARS + WRITER))


class Triage(unittest.TestCase):
    def test_train_classify_retries_the_stray(self):
        v = triage.classify({"id": "1"}, [job("d1-01-rust-test")], STRAY, {"cars": CARS})
        self.assertEqual(v["kind"], "runner")
        self.assertEqual(v["evidence"]["scratch"]["touched"], [])
        self.assertEqual(triage.classify({"id": "1"}, [job("d1-01-rust-test")], STRAY, {"cars": CARS + WRITER})["kind"], "car")

    def test_run_triage_is_runner_and_the_recheck_agrees(self):
        u = unit("records-check", "c3-01-records-check", ["##[error]" + STRAY.splitlines()[0]])
        v = one(u, cars=CARS, live={"02"})
        self.assertEqual((v["kind"], v["owner"], v["recheck"]), ("runner", None, "agrees"))
        self.assertEqual(check.recheck(v["evidence"]), ("runner", None))

    def test_run_triage_keeps_a_car_that_writes_it(self):
        u = unit("records-check", "c3-01-records-check", ["##[error]" + STRAY.splitlines()[0]])
        self.assertNotEqual(one(u, cars=CARS + WRITER, live={"05"})["kind"], "runner")


if __name__ == "__main__":
    unittest.main()
