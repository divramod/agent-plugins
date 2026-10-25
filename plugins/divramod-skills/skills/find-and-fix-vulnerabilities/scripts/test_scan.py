"""scan.py: collect -> report -> table (-> plan), on fakes and the KEV fixture; offline, nothing written outside tmp."""
import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scan
from testutil import HERE, FakeRunner, data, make_farm, ok, osv_argv


def run_scan(argv, runner):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = scan.main(argv, runner)
    return code, out.getvalue()


class Scan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.root = tmp / "a"
        self.farm = make_farm(self.root, "io")
        (tmp / "cache").mkdir()
        shutil.copy(HERE / "testdata" / "kev-fixture.json", tmp / "cache" / "kev.json")
        patch = mock.patch.dict(os.environ, {"HAL2_VULNS_CACHE": str(tmp / "cache")})
        patch.start()
        self.addCleanup(patch.stop)
        self.runner = FakeRunner({osv_argv(self.farm): ok(data("osv_v2.json"), 1)})

    def tearDown(self):
        self.tmp.cleanup()

    def test_table_of_farms_offline(self):
        code, out = run_scan(["--root", str(self.root), "--only", "farms", "--offline"], self.runner)
        self.assertEqual(code, 0)
        self.assertIn("vulnerabilities", out.splitlines()[0])
        self.assertIn("| CVE | where |", out)

    def test_outdated_hidden_by_default_and_shown_with_all(self):
        brew = FakeRunner({("brew", "outdated", "--json=v2"): ok('{"formulae":[{"name":"wget","installed_versions":["1"],'
                                                             '"current_version":"2"}],"casks":[]}')})
        _, out = run_scan(["--only", "os", "--offline"], brew)
        if "brew" not in str(brew.calls):
            self.skipTest("os collector does not call brew on this platform")
        self.assertIn("1 outdated packages hidden (--all)", out.splitlines()[0])
        self.assertNotIn("brew-outdated:wget", out)
        _, out = run_scan(["--only", "os", "--offline", "--all"], brew)
        self.assertIn("brew-outdated:wget", out)
        self.assertNotIn("hidden", out.splitlines()[0])

    def test_outdated_not_in_plan(self):
        import planwriter
        import report as report_mod
        from findings import Finding, Report
        rep = Report(generated="x")
        rep.findings = [Finding(id="brew-outdated:wget", target_kind="os", target="macos", package="wget", source="brew")]
        out = report_mod.build(rep, True, False, None, directory=Path(self.tmp.name) / "cache")
        self.assertEqual((out["findings"], out["hidden_outdated"]), ([], 1))
        self.assertIn("no findings", planwriter.write_plan(out, Path(self.tmp.name), True))

    def test_bad_part_is_exit_two(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code, _ = run_scan(["--only", "nope"], self.runner)
        self.assertEqual(code, 2)

    def test_plan_dry_run_writes_nothing(self):
        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        code, out = run_scan(["--root", str(self.root), "--only", "farms", "--offline", "--plan", "--dry-run",
                              "--repo", str(repo)], self.runner)
        self.assertEqual(code, 0)
        self.assertEqual(list(repo.iterdir()), [])

    def test_image_flag_scans_only_that_image(self):
        run_scan(["--root", str(self.root), "--only", "images", "--offline", "--image", "x:1"], self.runner)
        self.assertEqual([c[-1] for c in self.runner.calls if c[0] == "trivy"], ["x:1"])
        self.assertFalse(any(c[0] == "docker" for c in self.runner.calls))


if __name__ == "__main__":
    unittest.main()
