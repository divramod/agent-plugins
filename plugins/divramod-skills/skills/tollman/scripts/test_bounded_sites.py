"""The tollman's git and hal2-cli-git call sites run through the farmer's bounded.run (hal2 plan 0480 step 06.01,
L63): a stalled program ends within the limit, is tried twice, and the caller sees an error, not a hang. Fake
programs sit first on PATH in a scratch folder; the limits are tiny."""

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import bounded
import carrier
import engine
import trial
import yard

TINY = 0.4
STALL = 'echo x >> "$COUNT"\nsleep 300 &\nwait\n'


class Sites(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "bin").mkdir()
        patcher = mock.patch.dict(os.environ, {"PATH": f"{self.dir / 'bin'}:/usr/bin:/bin", "COUNT": str(self.dir / "n")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def stall(self, name, limit, call, *args, **kw):
        f = self.dir / "bin" / name
        f.write_text(f"#!/bin/sh\n{STALL}")
        f.chmod(0o755)
        with mock.patch.object(bounded, limit, TINY):
            t0 = time.monotonic()
            try:
                result = call(*args, **kw)
            except subprocess.TimeoutExpired as e:
                result = e
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(len((self.dir / "n").read_text().split()), 2, "one try and exactly one retry")
        (self.dir / "n").unlink()
        return result

    def test_the_carriers_and_the_trials_fetch_give_up_after_one_retry(self):
        top = str(self.dir)
        self.assertIsInstance(self.stall("git", "NETWORK_GIT", carrier.git, top, "fetch", "-q", "origin"), subprocess.TimeoutExpired)
        self.assertIsInstance(self.stall("git", "NETWORK_GIT", trial.git, top, "fetch", "origin"), subprocess.TimeoutExpired)

    def test_the_yards_git_and_the_engines_hal2_cli_git_end_within_their_limits(self):
        self.assertIsInstance(self.stall("git", "NETWORK_GIT", yard.run, str(self.dir), "fetch"), subprocess.TimeoutExpired)
        code, text = self.stall("hal2-cli-git", "HAL", engine.cli, ["worktree", "queue"], str(self.dir))
        self.assertEqual(code, 127)
        self.assertIn("timed out", text)


if __name__ == "__main__":
    unittest.main()
