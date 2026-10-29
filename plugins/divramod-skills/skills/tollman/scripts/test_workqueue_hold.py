"""Plan 0466 step 3: the tollman's workqueue hold releases on every exit and is optional (no real workqueue)."""

import os
import types
import unittest
from unittest import mock

import workqueue_hold

os.environ.setdefault("HAL2_WORKQUEUE_FREEZE", "0")


class Hold(unittest.TestCase):
    def test_a_crash_inside_the_hold_still_releases_it(self):
        calls = []

        def run(argv, **kw):
            calls.append(" ".join(argv[1:3]))
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with (mock.patch.object(workqueue_hold, "WQ", "fake-wq"), mock.patch.object(workqueue_hold.shutil, "which", lambda n: n),
              mock.patch.object(workqueue_hold.subprocess, "run", run), mock.patch("sys.stdout"), mock.patch.dict(os.environ)):
            os.environ.pop("HAL2_WORKQUEUE_FREEZE", None)
            with self.assertRaises(RuntimeError), workqueue_hold.landing_hold("/farm/x"):
                raise RuntimeError("boom")
        self.assertEqual(calls, ["hold take", "hold release"])

    def test_without_the_workqueue_cli_the_train_still_runs(self):
        with mock.patch.object(workqueue_hold.shutil, "which", lambda n: None), mock.patch("sys.stdout"), \
                mock.patch.dict(os.environ):
            os.environ.pop("HAL2_WORKQUEUE_FREEZE", None)
            with workqueue_hold.landing_hold("/farm/x"):
                self.assertNotIn("HAL2_WORKQUEUE_HOLD", os.environ)


if __name__ == "__main__":
    unittest.main()
