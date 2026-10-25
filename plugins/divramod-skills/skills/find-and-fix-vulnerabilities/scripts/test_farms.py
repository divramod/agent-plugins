import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import collect_farms
import findings as fx
from testutil import FakeRunner, data, make_farm, ok, osv_argv, osv_v1_argv


class Discovery(unittest.TestCase):
    def test_farms_are_checkouts_without_hidden_or_build_folders(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_farm(root, "io")
            make_farm(root, "hal2", git_file=True)
            make_farm(root, ".hidden")
            make_farm(root, "node_modules")
            make_farm(root, "target")
            (root / "notes").mkdir()
            (root / "file.txt").write_text("x")
            names = [f.name for f in collect_farms.discover_farms(root)]
            self.assertEqual(names, ["hal2", "io"])

    def test_worktree_replaces_its_main_checkout(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "a"
            make_farm(root, "hal2")
            make_farm(root, "io")
            wt = Path(d) / "worktree" / "hal2" / "12"
            wt.mkdir(parents=True)
            farms = collect_farms.discover_farms(root, wt)
            self.assertEqual(farms, [root / "io", wt])

    def test_missing_root_is_empty(self):
        self.assertEqual(collect_farms.discover_farms(Path("/nonexistent-root-xyz")), [])


class Scan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.io = make_farm(self.root, "io")
        self.empty = make_farm(self.root, "empty")
        self.bad = make_farm(self.root, "zbad")

    def tearDown(self):
        self.tmp.cleanup()

    def test_findings_skips_and_errors(self):
        runner = FakeRunner({
            osv_argv(self.empty): ok("", 128),
            osv_argv(self.io): ok(data("osv_v2.json"), 1),
            osv_argv(self.bad): ok("", 2, "boom"),
            osv_v1_argv(self.bad): ok("", 2, "boom v1"),
        })
        report = fx.Report()
        with mock.patch.dict(os.environ, {"HOME": "/home/test"}):
            farms = collect_farms.collect(runner, report, self.root)
        self.assertEqual([f.name for f in farms], ["empty", "io", "zbad"])
        self.assertEqual(len(report.findings), 3)
        self.assertEqual(report.skipped[0]["why"], "no lockfiles or manifests found")
        self.assertIn("rc 2", report.errors[0]["message"])
        self.assertIn("boom v1", report.errors[0]["message"])

    def test_v1_fallback_is_parsed(self):
        runner = FakeRunner({osv_argv(self.empty): ok("", 128), osv_argv(self.bad): ok("", 128),
                             osv_argv(self.io): ok("", 2, "unknown flag"),
                             osv_v1_argv(self.io): ok(data("osv_v2.json"), 1)})
        report = fx.Report()
        collect_farms.collect(runner, report, self.root)
        self.assertEqual(len(report.findings), 3)

    def test_missing_osv_scanner_is_one_error_not_a_crash(self):
        report = fx.Report()
        collect_farms.collect(FakeRunner(), report, self.root)
        self.assertEqual(report.errors, [{"target": "osv-scanner", "message": "osv-scanner not installed"}])
        self.assertEqual(report.findings, [])

    def test_scan_is_read_only_osv_command(self):
        runner = FakeRunner({osv_argv(self.io): ok("{}", 0)})
        collect_farms.collect(runner, fx.Report(), self.root)
        self.assertEqual(runner.calls[0][:6], ["osv-scanner", "scan", "source", "-r", "--format", "json"])

    def test_garbage_output_is_an_error(self):
        runner = FakeRunner({osv_argv(f): ok("<html>", 0) for f in (self.io, self.empty, self.bad)})
        report = fx.Report()
        collect_farms.collect(runner, report, self.root)
        self.assertEqual(len(report.errors), 3)


if __name__ == "__main__":
    unittest.main()
