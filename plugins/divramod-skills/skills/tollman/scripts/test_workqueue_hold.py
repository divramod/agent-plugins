"""Plan 0466 step 3: the tollman's workqueue hold releases on every exit and is optional (no real workqueue)."""

import os
import tempfile
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


class Cloud(unittest.TestCase):
    """Plan 0467 D37: which train lands through merge-to-main-cloud, as hal2-git's ci/choice.rs picks it."""

    def tree(self, setting, with_file=True):
        top = tempfile.mkdtemp()
        os.makedirs(f"{top}/.hal")
        os.makedirs(f"{top}/.github/workflows")
        if setting:
            with open(f"{top}/.hal/landing.toml", "w") as f:
                f.write(f'# chooses\nworkflow = "{setting}"\n')
        if with_file:
            open(f"{top}/.github/workflows/merge-to-main-cloud.yml", "w").close()
        return top

    def test_the_file_and_the_variable_choose(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("HAL2_LAND_WORKFLOW", None)
            self.assertTrue(workqueue_hold.cloud_train(self.tree("cloud")))
            self.assertFalse(workqueue_hold.cloud_train(self.tree("local")))
            self.assertFalse(workqueue_hold.cloud_train(self.tree(None)))
            self.assertFalse(workqueue_hold.cloud_train(self.tree("cloud", with_file=False)), "no such workflow: local")
            os.environ["HAL2_LAND_WORKFLOW"] = "local"
            self.assertFalse(workqueue_hold.cloud_train(self.tree("cloud")), "the variable wins")
            os.environ["HAL2_LAND_WORKFLOW"] = "cloud"
            self.assertTrue(workqueue_hold.cloud_train(self.tree(None)))

    def test_a_cloud_train_takes_no_hold(self):
        calls = []
        with (mock.patch.object(workqueue_hold, "WQ", "fake-wq"), mock.patch.object(workqueue_hold.shutil, "which", lambda n: n),
              mock.patch.object(workqueue_hold.subprocess, "run", lambda argv, **kw: calls.append(argv)),
              mock.patch("sys.stdout"), mock.patch.dict(os.environ)):
            os.environ.pop("HAL2_WORKQUEUE_FREEZE", None)
            os.environ.pop("HAL2_LAND_WORKFLOW", None)
            with workqueue_hold.landing_hold(self.tree("cloud")):
                self.assertNotIn("HAL2_WORKQUEUE_HOLD", os.environ)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
