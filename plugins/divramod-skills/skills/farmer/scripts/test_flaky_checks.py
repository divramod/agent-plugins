"""Hal2 plan 0289 step 3: the farmer's flaky candidates from `hal2-cli-git worktree checks --json` where the CLI
knows it, else from its own count; the same cases hold with a fake CLI on PATH and with none."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import flaky_checks
import mtm_scan as scan
from test_mtm_scan import snap

CHECKS = {"checks": [], "flaky": [
    {"test": "twice", "count": 2, "fields": ["12"], "last": "2026-10-17T10:00:00Z"},
    {"test": "two_fields", "count": 2, "fields": ["01", "09"], "last": "2026-10-17T10:00:00Z"}]}
# What the farmer's own landing count makes of the same three cases (red twice, two fields, once).
OWN = {"twice": {"test": "twice", "failures": 2, "slots": ["12"]},
       "two_fields": {"test": "two_fields", "failures": 2, "slots": ["01", "09"]},
       "once": {"test": "once", "failures": 1, "slots": ["01"]}}


def candidates(tests):
    return sorted(f["test"] for f in scan.findings(snap(tests=tests)) if f["kind"] == "flaky-candidate")


class FakeCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        flaky_checks.reset()
        self.addCleanup(flaky_checks.reset)

    def path_with(self, body: str | None):
        """PATH holding a fake `hal2-cli-git` printing `body` (none: an empty folder, no CLI)."""
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir(exist_ok=True)
        if body is not None:
            f = bin_dir / "hal2-cli-git"
            f.write_text(f"#!/bin/sh\nif [ \"$2\" = checks ]; then cat <<'EOF'\n{body}\nEOF\nelse exit 2; fi\n")
            f.chmod(f.stat().st_mode | stat.S_IXUSR)
        return mock.patch.dict(os.environ, {"PATH": f"{bin_dir}:/usr/bin:/bin"})

    def cli_tests(self, body):
        flaky_checks.reset()
        with self.path_with(body):
            return flaky_checks.tests(scan.run_json, self.tmp.name)

    def test_a_cli_that_knows_checks_is_the_source(self):
        got = self.cli_tests(json.dumps(CHECKS))
        self.assertEqual(got["two_fields"], OWN["two_fields"])
        self.assertEqual(candidates(got), ["twice", "two_fields"])

    def test_no_cli_or_an_older_one_leaves_the_own_count(self):
        self.assertIsNone(self.cli_tests(None))
        self.assertIsNone(self.cli_tests("not json"))
        self.assertIsNone(self.cli_tests('{"queue": []}'))
        self.assertEqual(candidates(OWN), ["twice", "two_fields"])

    def test_same_cases_with_and_without_the_cli(self):
        # red twice, two fields: candidates; once: not (the CLI lists only the flaky, the own count filters).
        self.assertEqual(candidates(self.cli_tests(json.dumps(CHECKS))), candidates(OWN))

    def test_the_probe_runs_once_per_checkout(self):
        calls = []
        run_json = lambda args, cwd=None: calls.append(args) or CHECKS
        flaky_checks.tests(run_json, "/x")
        flaky_checks.tests(run_json, "/x")
        self.assertEqual(len(calls), 1)

    def test_snapshot_takes_the_cli_list_over_its_own(self):
        d = self.tmp.name
        answers = lambda args, cwd=None: CHECKS if args[:3] == ["hal2-cli-git", "worktree", "checks"] else None
        with mock.patch.object(scan, "run", return_value=""), mock.patch.object(scan, "run_json", answers), \
                mock.patch.object(scan, "worktrees", return_value=[]), \
                mock.patch.object(scan.mtm_ci, "ci_mode", return_value=True), \
                mock.patch.object(scan.mtm_ci, "landings", return_value=[]), \
                mock.patch.object(scan.mtm_ci, "unfinished", return_value=0), \
                mock.patch.object(scan, "state_dir", return_value=Path(d) / "state"):
            got = scan.snapshot(d, 24, fetch=False)
        self.assertEqual(sorted(got["tests"]), ["twice", "two_fields"])
        self.assertEqual([f["test"] for f in got["findings"] if f["kind"] == "flaky-candidate"],
                         ["twice", "two_fields"])


if __name__ == "__main__":
    unittest.main()
