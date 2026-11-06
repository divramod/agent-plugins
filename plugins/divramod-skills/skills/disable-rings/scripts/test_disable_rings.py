#!/usr/bin/env python3
"""Tests for disable_rings.py with a fake hal2-cli-ring on PATH (offline)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
SCRIPT = HERE / "disable_rings.py"

FAKE = """#!/bin/sh
printf '%s\\n' "$@" > "$FAKE_ARGV"
[ -n "$FAKE_FAIL" ] && { echo "boom" >&2; exit 3; }
cat "$FAKE_OUT"
"""


class DisableRings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        fake = self.bin / "hal2-cli-ring"
        fake.write_text(FAKE)
        fake.chmod(0o755)
        self.argv = self.dir / "argv"
        self.out = self.dir / "out.json"
        self.out.write_text(json.dumps({"schema": 1, "mode": "off", "until": "2026-11-05T12:00:00Z"}))

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args, path=None, fail=False):
        env = {"PATH": path if path is not None else f"{self.bin}:/usr/bin:/bin",
               "FAKE_ARGV": str(self.argv), "FAKE_OUT": str(self.out)}
        if fail:
            env["FAKE_FAIL"] = "1"
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env)

    def called(self):
        return self.argv.read_text().split()

    def test_no_args_is_off(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.called(), ["mode", "off", "--from", "disable-rings", "--json"])
        self.assertIn("off until 2026-11-05T12:00:00Z", r.stdout)
        self.assertIn("/disable-rings on", r.stdout)

    def test_silent_for(self):
        self.out.write_text(json.dumps({"mode": "silent", "until": None}))
        r = self.run_script("silent", "--for", "2h")
        self.assertEqual(self.called(),
                         ["mode", "silent", "--for", "2h", "--from", "disable-rings", "--json"])
        self.assertIn("silent until changed", r.stdout)

    def test_off_for(self):
        self.run_script("off", "--for", "2h")
        self.assertEqual(self.called(), ["mode", "off", "--for", "2h", "--from", "disable-rings", "--json"])

    def test_on_is_ring(self):
        self.out.write_text(json.dumps({"mode": "ring", "until": None}))
        r = self.run_script("on")
        self.assertEqual(self.called(), ["mode", "ring", "--from", "disable-rings", "--json"])
        self.assertIn("ring: rings with sound", r.stdout)

    def test_on_rejects_for(self):
        self.assertEqual(self.run_script("on", "--for", "1h").returncode, 64)

    def test_status_sets_nothing(self):
        r = self.run_script("status")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.called(), ["mode", "--json"])

    def test_bad_call(self):
        r = self.run_script("sauna")
        self.assertEqual(r.returncode, 64)
        self.assertFalse(self.argv.exists())

    def test_missing_cli(self):
        r = self.run_script("status", path="/usr/bin:/bin")
        self.assertEqual(r.returncode, 2)
        self.assertIn("hal2-cli-ring is not installed", r.stderr)

    def test_cli_failure(self):
        r = self.run_script("off", fail=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("boom", r.stderr)

    def test_help_table(self):
        for word in ("h", "help"):
            r = self.run_script(word, path="/usr/bin:/bin")
            self.assertEqual(r.returncode, 0)
            for call in ("/disable-rings off", "/disable-rings silent", "/disable-rings on", "/disable-rings status"):
                self.assertIn(call, r.stdout)


if __name__ == "__main__":
    unittest.main()
