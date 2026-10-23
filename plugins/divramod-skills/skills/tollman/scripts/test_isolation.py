"""Hal2 plan 0412 step 5 (the tollman's message 05-t1): a test never reaches the tollman's real state. Under a test
(`roles.UNDER_TEST`, which test_farmer.Repo sets with its own temp `FARMER_DIR`) the state folder resolver refuses
any folder outside the temp dir before it creates or writes anything, and the child processes a test starts inherit
the temp state folder instead of resolving the live `roles/tollman/`."""
# enforces .adr/no-committed-runtime-state.md and .adr/tollman.md

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import roles
import train_state
from test_tollman import Field

HOME = Path("/nonexistent-hal2-home")  # outside the temp dir, and no folder is ever made there
LIVE = HOME / ".hal/git/worktree/hal2/tollman-hal2/roles/tollman"


class Refuses(unittest.TestCase):
    def test_under_a_test_only_a_folder_in_the_temp_dir_is_a_state_folder(self):
        env = {roles.UNDER_TEST: "1"}
        with tempfile.TemporaryDirectory() as tmp:
            roles.refuse_real_state(Path(tmp) / "hal2" / "tollman", "tollman", env)
        with self.assertRaises(roles.RealStateRefused) as caught:
            roles.refuse_real_state(LIVE, "tollman", env)
        self.assertIn("refusing the tollman state folder", str(caught.exception))
        self.assertIn(roles.UNDER_TEST, str(caught.exception))

    def test_without_the_mark_every_folder_is_a_state_folder(self):
        roles.refuse_real_state(LIVE, "tollman", {})
        roles.refuse_real_state(LIVE, "tollman", {roles.UNDER_TEST: ""})


class Reaches(Field):
    def test_the_train_state_writer_refuses_the_live_folder_and_writes_nothing(self):
        self.assertEqual(os.environ.get(roles.UNDER_TEST), "1", "test_farmer.Repo marks every test of a farm")
        with mock.patch.object(roles.Path, "home", return_value=HOME), mock.patch.object(mtm_scan, "DATA", None):
            with self.assertRaises(roles.RealStateRefused):
                train_state.append(str(self.main), "run", "tollman-train-0001", run="https://github.com/x/actions/runs/720")
            with self.assertRaises(roles.RealStateRefused):
                train_state.next_number(str(self.main))
        self.assertFalse(HOME.exists(), "nothing was made at the live path")

    def test_the_train_state_writer_writes_the_test_s_own_folder(self):
        train_state.append(str(self.main), "run", "tollman-train-0001", run="https://github.com/x/actions/runs/720")
        own = self.data / "hal2" / "tollman" / train_state.FILE
        self.assertEqual([r["kind"] for r in train_state.lines(str(self.main))], ["run"])
        self.assertTrue(own.is_file(), own)

    def test_a_child_process_resolves_the_test_s_folder_not_the_live_one(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import mtm_scan; "
                "print(mtm_scan.state_dir(sys.argv[2], 'tollman'))")
        run = subprocess.run([sys.executable, "-c", code, str(farmer_frame.SCRIPTS), str(self.main)],
                             capture_output=True, text=True, env={**os.environ, "HOME": str(HOME)})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(Path(run.stdout.strip()), self.data / "hal2" / "tollman")

    def test_a_child_process_without_the_temp_folder_is_refused(self):
        env = {k: v for k, v in os.environ.items() if k != "FARMER_DIR"}
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import mtm_scan; "
                "mtm_scan.state_dir(sys.argv[2], 'tollman')")
        run = subprocess.run([sys.executable, "-c", code, str(farmer_frame.SCRIPTS), str(self.main)],
                             capture_output=True, text=True, env={**env, "HOME": str(HOME)})
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("RealStateRefused", run.stderr)


if __name__ == "__main__":
    unittest.main()
