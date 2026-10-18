#!/usr/bin/env python3
"""Tests for restart.py with a fake hal2-cli-agents on PATH (offline: nothing is restarted)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
print(os.environ["FAKE_OUT"])
'''

ROWS = [
    {"pane_id": "%3", "slot": "03", "project": "/x/hal2", "action": "restart", "result": "restarted"},
    {"pane_id": "%4", "slot": "04", "project": "/x/hal2", "action": "skip", "reason": "landing held", "result": "skipped"},
    {"pane_id": "%5", "slot": "05", "project": "/x/hal2", "action": "caller-last", "result": "restarted"},
]


class RestartTest(unittest.TestCase):
    def run_script(self, rows, *args, path=True):
        with tempfile.TemporaryDirectory() as d:
            bindir = Path(d) / "bin"
            bindir.mkdir()
            fake = bindir / "hal2-cli-agents"
            fake.write_text(FAKE)
            fake.chmod(0o755)
            env = dict(os.environ, FAKE_LOG=str(Path(d) / "log"), FAKE_OUT=json.dumps(rows),
                       PATH=f"{bindir}:{os.environ['PATH']}" if path else "/nonexistent")
            r = subprocess.run([sys.executable, str(HERE / "restart.py"), *args], capture_output=True, text=True, env=env)
            log = Path(d, "log")
            calls = [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []
            return r, calls

    def test_passes_flags_through_and_prints_table(self):
        r, calls = self.run_script(ROWS, "--dry-run", "--except", "%9", "--wait", "30")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls, [["restart", "--all", "--json", "--dry-run", "--except", "%9", "--wait", "30"]])
        self.assertIn("hal2/03", r.stdout)
        self.assertIn("skipped (landing held)", r.stdout)
        self.assertNotIn("restarts last", r.stdout)  # dry run

    def test_caller_last_note(self):
        r, _ = self.run_script(ROWS)
        self.assertIn("restarts last", r.stdout)

    def test_failed_exits_one(self):
        r, _ = self.run_script(ROWS + [dict(ROWS[0], pane_id="%6", result="failed")])
        self.assertEqual(r.returncode, 1)

    def test_missing_cli_exits_two(self):
        r, _ = self.run_script(ROWS, path=False)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
