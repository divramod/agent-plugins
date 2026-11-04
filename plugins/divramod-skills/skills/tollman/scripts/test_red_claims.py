"""One red, one foreman (red_claims.py, the user 2026-11-04): an order of a run's red job to a second field is
refused unless it names a different failing test; the same field is orders.order's (`also`); the check and the
write happen under one lock."""
# enforces .adr/tollman.md

import fcntl
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import red_claims

RUN = "https://github.com/divramod/hal2/actions/runs/41824763199"


def line(field, oid, jobs=(), why="", units=None, run="41824763199", also=None):
    return {"kind": "order", "field": field, "id": oid, "jobs": list(jobs), "why": why, "run": run,
            **({"units": units} if units else {}), **({"also": also} if also else {})}


class Clash(unittest.TestCase):
    def test_second_field_for_the_same_job_is_refused(self):
        rows = [line("55", "55-fix-4", ["bash-build-test-mac"], "c4-01-bash-build-test-mac: ci-runner-linux 48")]
        why = red_claims.clash(rows, "61", RUN, ["bash-build-test-mac"], [])
        self.assertIn("went to 55 already (55-fix-4)", why)

    def test_a_job_named_only_in_the_why_counts(self):
        rows = [line("47", "47-fix-3", ["rust-release-linux"],
                     "c2-01-rust-release-linux: x; c2-06-python-build-test-linux: y")]
        self.assertIn("python-build-test-linux", red_claims.clash(rows, "33", RUN, ["python-build-test-linux"], []))

    def test_a_different_unit_of_the_same_job_goes_to_its_own_foreman(self):
        rows = [line("55", "55-fix-4", ["bash-build-test-mac"], "ci-runner-linux/test.bats 48",
                     units=["ci-runner-linux/test.bats 48"])]
        self.assertIsNone(red_claims.clash(rows, "61", RUN, ["bash-build-test-mac"], ["deliver/test.bats 73"]))

    def test_the_same_unit_is_refused_also_when_only_the_why_names_it(self):
        rows = [line("55", "55-fix-4", ["bash-build-test-mac"], "deliver/test.bats 53 after cbdf785a05")]
        why = red_claims.clash(rows, "61", RUN, ["bash-build-test-mac"], ["deliver/test.bats 53"])
        self.assertIn("unit deliver/test.bats 53", why)

    def test_the_same_field_and_other_runs_and_main_are_no_clash(self):
        rows = [line("55", "55-fix-4", ["lint"]), line("47", "47-fix-1", ["lint"], run="999")]
        self.assertIsNone(red_claims.clash(rows, "55", RUN, ["lint"], []))
        self.assertIsNone(red_claims.clash(rows, "47", "1", ["lint"], []))
        self.assertIsNone(red_claims.clash(rows, "main", RUN, ["lint"], []))

    def test_jobs_of_reads_staged_names(self):
        self.assertEqual(red_claims.jobs_of(["lint"], "c4-01-bash-build-test-mac: x, c2-02-lint: y"),
                         ["lint", "bash-build-test-mac"])


class Order(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rows = [{"kind": "formed", "train": "T", "cars": []}, {"kind": "run", "train": "T", "run": RUN},
                     line("55", "55-fix-4", ["bash-build-test-mac"], "c4-01-bash-build-test-mac: ci-runner 48")]
        self.calls = []
        for p in (mock.patch.object(red_claims.mtm_scan, "main_checkout", lambda top: top),
                  mock.patch.object(red_claims.train_state, "folder", lambda main: Path(self.tmp.name)),
                  mock.patch.object(red_claims.train_state, "lines", lambda main: list(self.rows)),
                  mock.patch.object(red_claims.orders, "order", self.fake_order)):
            p.start()
            self.addCleanup(p.stop)

    def fake_order(self, *a, **kw):
        with (Path(self.tmp.name) / red_claims.LOCK).open("a") as f:  # the lock is held while the order is written
            with self.assertRaises(BlockingIOError):
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.calls.append((a, kw))
        return 0, "ordered", []

    def test_a_clash_writes_and_sends_nothing(self):
        code, text, actions = red_claims.order("/m", "61", "c4-01-bash-build-test-mac: deliver 73", RUN, {})
        self.assertEqual((code, actions, self.calls), (1, [], []))
        self.assertIn("one red, one foreman", text)

    def test_a_named_distinct_unit_is_ordered_with_its_units(self):
        code, _, _ = red_claims.order("/m", "61", "c4-01-bash-build-test-mac: deliver 73", RUN, {},
                                      units=["deliver/test.bats 73", " "])
        self.assertEqual(code, 0)
        self.assertEqual(self.calls[0][1]["units"], ["deliver/test.bats 73"])

    def test_the_run_defaults_to_the_trains(self):
        code, _, _ = red_claims.order("/m", "61", "c4-01-bash-build-test-mac: deliver 73", None, {})
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
