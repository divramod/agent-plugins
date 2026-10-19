"""Tests of proc.py: the bounded child process and its process group (review 5 of plan 0390 step 6)."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import proc

SPAWN = """
import subprocess, sys
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(child.pid, flush=True)
"""


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def gone_within(pid, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


@unittest.skipIf(os.name == "nt", "process groups are POSIX")
class ProcTest(unittest.TestCase):
    def test_result_of_a_normal_end(self):
        out = proc.run([sys.executable, "-c", "print('hi')"], cwd=tempfile.gettempdir(), env=dict(os.environ))
        self.assertEqual((out["code"], out["timed_out"], out["out"].strip(), out["error"]), (0, False, b"hi", None))

    def test_regression_background_process_dies_with_the_run(self):  # review 5
        out = proc.run([sys.executable, "-c", SPAWN], cwd=tempfile.gettempdir(), env=dict(os.environ), timeout=30)
        self.assertEqual(out["code"], 0, out["err"])
        pid = int(out["out"].strip())
        self.assertTrue(gone_within(pid), f"background process {pid} outlived the run")

    def test_timeout_kills_the_group(self):
        out = proc.run([sys.executable, "-c", SPAWN + "import time; time.sleep(60)\n"], cwd=tempfile.gettempdir(),
                       env=dict(os.environ), timeout=1)
        self.assertTrue(out["timed_out"])
        self.assertIsNone(out["code"])
        pid = int(out["out"].strip())
        self.assertTrue(gone_within(pid))

    def test_start_failure(self):
        out = proc.run([str(Path(tempfile.gettempdir()) / "no-such-program")], cwd=tempfile.gettempdir(),
                       env=dict(os.environ))
        self.assertIsNotNone(out["error"])


if __name__ == "__main__":
    unittest.main()
