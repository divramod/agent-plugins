"""Prune's hands (prune_act.py; first the tollman's, copied by plan 0377 step 3, rebuilt by step 5): a removal stops the
resting sessions by signal first and runs without a timeout (D7), a servant's is forced and its origin branch deleted
only once in its foreman's, muck out and trim go through the cleanup skill. hal2-cli-git and the session stop are
fakes that record their calls; git runs on a scratch farm. The proof before each hand is executor.py's (test_executor)."""

import subprocess
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import prune_act
import prune_proof
from worktree_farm import MarkedSlots, Slots
from test_farmer import git


class Hands(Slots):
    def setUp(self):
        super().setUp()
        # The host's own processes never decide a test: no build runs in a fixture's field.
        quiet = mock.patch.object(prune_proof, "build_running", return_value=False)
        quiet.start()
        self.addCleanup(quiet.stop)
        self.calls = []
        patcher = mock.patch.object(prune_act, "run", side_effect=lambda argv, cwd: self.calls.append(argv) or (0, "removed"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.field = {"slot": "13", "path": str(self.base / "13")}

    def test_remove_stops_the_idle_session_by_signal_then_removes_with_the_remote_branch(self):
        with mock.patch.object(prune_act, "stop", return_value=None) as stop:
            self.assertEqual(prune_act.remove(str(self.main), self.field, None, ["%7"]), ("success", "removed"))
        stop.assert_called_once_with(str(self.main), "%7")
        self.assertEqual(self.calls, [["hal2-cli-git", "worktree", "remove", "13", "--remote"]])

    def test_a_draft_in_the_prompt_skips_the_removal(self):
        with mock.patch.object(prune_act, "stop", return_value="draft: the input box holds \"x\""):
            status, text = prune_act.remove(str(self.main), self.field, None, ["%7"])
        self.assertEqual(status, "skipped")
        self.assertIn("%7: not stopped: draft", text)
        self.assertEqual(self.calls, [])

    def test_a_resumed_removal_is_forced(self):
        prune_act.remove_cmd(str(self.main), "13", None, force=True)
        self.assertEqual(self.calls, [["hal2-cli-git", "worktree", "remove", "13", "--remote", "--force"]])


class NoTimeout(unittest.TestCase):
    def test_d7_a_command_runs_without_a_timeout(self):
        with mock.patch.object(prune_act.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="ok", stderr="")) as run:
            self.assertEqual(prune_act.run(["true"], "/"), (0, "ok"))
        self.assertNotIn("timeout", run.call_args.kwargs)

    def test_a_missing_program_is_127(self):
        self.assertEqual(prune_act.run(["hal2-no-such-tool-for-prune-tests"], "/")[0], 127)


class Clean(Slots):
    def test_muck_out_runs_the_cleanup_skill(self):
        (self.main / ".gitignore").write_text("target/\n")
        (self.base / "03/.gitignore").write_text("target/\n")
        git(self.base / "03", "add", ".gitignore")
        git(self.base / "03", "commit", "-qm", "ignore")
        (self.base / "03/target").mkdir()
        (self.base / "03/target/x.o").write_text("x")
        with mock.patch.dict("os.environ", {"HAL_CLEANUP_CLI": ""}):
            status, text = prune_act.clean({"path": str(self.base / "03")}, None)
        self.assertEqual(status, "success", text)
        self.assertFalse((self.base / "03/target").exists())

    def test_a_trim_path_that_is_not_there_is_nothing_to_do(self):
        with mock.patch.dict("os.environ", {"HAL_CLEANUP_CLI": ""}):
            status, text = prune_act.clean({"path": str(self.base / "03")}, ["code/rust/target"])
        self.assertEqual((status, text), ("success", "nothing to trim: code/rust/target not there"))


class Servants(MarkedSlots):
    def setUp(self):
        super().setUp()
        # The host's own processes never decide a test: no build runs in a fixture's field.
        quiet = mock.patch.object(prune_proof, "build_running", return_value=False)
        quiet.start()
        self.addCleanup(quiet.stop)
        self.calls = []
        patcher = mock.patch.object(prune_act, "run", side_effect=self.run_cmd)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cmd(self, argv, cwd):
        self.calls.append(argv)
        if argv[0] == "hal2-cli-git":
            return 0, "removed"
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr).strip()

    def remote(self, name):
        return subprocess.run(["git", "ls-remote", "origin", f"refs/heads/{name}"], cwd=self.main,
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_pr7_a_servant_is_forced_out_then_origin_nn_deleted(self):
        status, text = prune_act.remove_subservant(str(self.main), "31", "02")
        self.assertEqual(status, "success", text)
        self.assertEqual(self.calls, [["hal2-cli-git", "worktree", "remove", "31", "--force"],
                                      ["git", "push", "--quiet", "origin", "--delete", "31"]])
        self.assertFalse(self.remote("31"))
        self.assertTrue(self.remote("02"))

    def test_origin_nn_holding_commits_its_foreman_lacks_is_kept(self):
        status, text = prune_act.remove_subservant(str(self.main), "32", "02")
        self.assertEqual(status, "failure")
        self.assertIn("origin/32 kept: it holds commits not in origin/02", text)
        self.assertTrue(self.remote("32"))


if __name__ == "__main__":
    unittest.main()
