"""The tollman's git and hal2-cli-git call sites run through the farmer's bounded.run (hal2 plan 0480 step 06.01,
L63): a stalled program ends within the limit, is tried twice, and the caller sees an error, not a hang. Fake
programs sit first on PATH in a scratch folder; the limits are tiny, and start only once the fake stalls (the farmer's
stall_fake.py, plan 0532 step 16): no machine is too slow for them. `FAKE_SLOW=<s>` delays every fake's start."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import bounded
import carrier
import engine
import trial
import yard
from stall_fake import STALL, cut, fake, install

TINY = 0.4


class Sites(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "bin").mkdir()
        patcher = mock.patch.dict(os.environ, {"PATH": f"{self.dir / 'bin'}:/usr/bin:/bin", "COUNT": str(self.dir / "n"),
                                               **install(self, self.dir)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def stall(self, name, limit, call, *args, **kw):
        fake(self.dir / "bin" / name, STALL)
        with mock.patch.object(bounded, limit, TINY):
            try:
                result = call(*args, **kw)
            except subprocess.TimeoutExpired as e:
                result = e
        cut(self, self.dir)  # the limit ended it, not the stall's 300 s
        self.assertEqual(len((self.dir / "n").read_text().split()), 2, "one try and exactly one retry")
        (self.dir / "n").unlink()
        return result

    def test_the_carriers_and_the_trials_fetch_give_up_after_one_retry(self):
        top = str(self.dir)
        code, text = self.stall("git", "NETWORK_GIT", carrier.git, top, "fetch", "-q", "origin")
        self.assertEqual(code, carrier.TIMED_OUT, "the carrier's timeout is exit 124, never an exception (plan 0490 row 10)")
        self.assertIn("timed out", text)
        self.assertIsInstance(self.stall("git", "NETWORK_GIT", trial.git, top, "fetch", "origin"), subprocess.TimeoutExpired)

    def test_the_yards_git_and_the_engines_hal2_cli_git_end_within_their_limits(self):
        self.assertIsInstance(self.stall("git", "NETWORK_GIT", yard.run, str(self.dir), "fetch"), subprocess.TimeoutExpired)
        code, text = self.stall("hal2-cli-git", "HAL", engine.cli, ["worktree", "queue"], str(self.dir))
        self.assertEqual(code, 127)
        self.assertIn("timed out", text)


if __name__ == "__main__":
    unittest.main()
