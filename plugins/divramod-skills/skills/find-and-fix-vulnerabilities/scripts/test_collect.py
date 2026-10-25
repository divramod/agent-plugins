"""The CLI: parts, the Report it prints, exit codes; the collectors themselves are tested beside it."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import collect
import collect_os
import collect_servers
from testutil import FakeRunner, data, make_farm, ok, osv_argv, ssh_argv


def run_cli(argv, runner):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = collect.main(argv, runner)
    return code, out.getvalue()


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "a"
        self.io = make_farm(self.root, "io")
        self.cfg = Path(self.tmp.name) / "servers.toml"
        self.cfg.write_text('[[server]]\nname = "hz01"\nhost = "h1"\n')

    def tearDown(self):
        self.tmp.cleanup()

    def base(self, *extra):
        return ["--root", str(self.root), "--servers-config", str(self.cfg), *extra]

    def test_json_report_of_all_parts_exits_zero_with_findings(self):
        runner = FakeRunner({
            osv_argv(self.io): ok(data("osv_v2.json"), 1),
            ("docker", "images", "--format", "{{.Repository}}:{{.Tag}}"): ok("node:22-slim\n"),
            tuple(collect_servers.collect_os.APT.split()): ok(data("apt.txt")),
            ssh_argv("h1", collect_os.APT): ok(data("apt.txt")),
            ssh_argv("h1", collect_servers.TRIVY_WHICH): ok("", 1),
        })
        with mock.patch.dict(os.environ, {"HOME": "/home/test"}), mock.patch("platform.system", return_value="Linux"):
            code, out = run_cli(self.base("--json"), runner)
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["schema"], 1)
        self.assertEqual({f["target_kind"] for f in report["findings"]}, {"farm", "os"})
        self.assertTrue(any(e["target"] == "trivy" for e in report["errors"]))  # docker image but no trivy

    def test_only_limits_the_parts(self):
        runner = FakeRunner({ssh_argv("h1", collect_os.APT): ok(data("apt.txt")),
                             ssh_argv("h1", collect_servers.TRIVY_WHICH): ok("", 1)})
        code, out = run_cli(self.base("--only", "servers", "--json"), runner)
        self.assertEqual(code, 0)
        self.assertTrue(all(c[0] == "ssh" for c in runner.calls))
        self.assertEqual({f["target"] for f in json.loads(out)["findings"]}, {"hz01"})

    def test_default_output_is_a_summary(self):
        code, out = run_cli(self.base("--only", "farms"), FakeRunner())
        self.assertEqual(code, 0)
        self.assertIn("0 findings", out)
        self.assertIn("error: osv-scanner: osv-scanner not installed", out)

    def test_bad_arguments_exit_two(self):
        for argv in (["--only", "moon"], ["--only", ""], ["--vm-mount", "nopath"], ["--nope"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                collect.main(argv, FakeRunner())
            self.assertEqual(cm.exception.code, 2, argv)

    def test_vm_mount_is_passed_on(self):
        args = collect.parse_args(["--vm-mount", "vm1=/Volumes/x", "--vm-mount", "vm2=/y"])
        self.assertEqual(args.mounts, {"vm1": "/Volumes/x", "vm2": "/y"})


if __name__ == "__main__":
    unittest.main()
