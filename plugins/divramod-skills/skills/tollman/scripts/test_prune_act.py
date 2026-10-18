"""The prune duty's hands (prune_act.py, the tollman's since plan 0360 step 7): `clean` and `remove` check the field
again and refuse one that holds work. hal2-cli-git and the session stop are fakes; git runs on a scratch farm."""

import contextlib
import io
import subprocess
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import prune
import prune_act
import prune_proof
import tick
from worktree_farm import MarkedSlots, Slots
from test_farmer import git


class Act(Slots):
    def setUp(self):
        super().setUp()
        live = mock.patch.object(prune_act, "live", return_value=({}, []))
        live.start()
        self.addCleanup(live.stop)
        # The host's own processes never decide a test: no build runs in a fixture's field.
        quiet = mock.patch.object(prune_proof, "build_running", return_value=False)
        quiet.start()
        self.addCleanup(quiet.stop)

    def test_refused_when_the_slot_holds_work_or_the_range_is_wrong(self):
        self.assertIn("uncommitted", prune_act.act_on(str(self.main), "04", "clean", True)[1])
        self.assertIn("10-99", prune_act.act_on(str(self.main), "03", "remove", True)[1])
        self.assertIn("00-09", prune_act.act_on(str(self.main), "13", "clean", True)[1])
        self.assertIn("no numbered worktree", prune_act.act_on(str(self.main), "42", "remove", True)[1])

    def test_clean_runs_the_cleanup_skill(self):
        (self.main / ".gitignore").write_text("target/\n")
        (self.base / "03/.gitignore").write_text("target/\n")
        git(self.base / "03", "add", ".gitignore")
        git(self.base / "03", "commit", "-qm", "ignore")
        git(self.base / "03", "push", "-q", "origin", "HEAD:main")
        git(self.base / "03", "fetch", "-q")
        (self.base / "03/target").mkdir()
        (self.base / "03/target/x.o").write_text("x")
        code, text = prune_act.act_on(str(self.main), "03", "clean", False)
        self.assertEqual(code, 0, text)
        self.assertFalse((self.base / "03/target").exists())

    def test_remove_stops_the_idle_session_by_signal_then_removes_with_the_remote_branch(self):
        agent = {"pane_id": "%7", "checkout": str(self.base / "13"), "state": "idle", "since": 0}
        calls = []
        with mock.patch.object(prune_act, "live", return_value=({}, [agent])), \
                mock.patch.object(prune_act, "stop", return_value=None) as stop, \
                mock.patch.object(tick, "sh", side_effect=lambda argv, cwd, timeout=900: calls.append((argv, cwd))
                                  or (0, "removed")):
            code, text = prune_act.act_on(str(self.main), "13", "remove", False)
        self.assertEqual((code, text), (0, "removed"))
        stop.assert_called_once_with(str(self.main), "%7")
        self.assertEqual(calls, [(["hal2-cli-git", "worktree", "remove", "13", "--remote"], str(self.main))])

    def test_a_draft_in_the_prompt_refuses_the_removal(self):
        agent = {"pane_id": "%7", "checkout": str(self.base / "13"), "state": "idle", "since": 0}
        with mock.patch.object(prune_act, "live", return_value=({}, [agent])), \
                mock.patch.object(prune_act, "stop", return_value="draft: the input box holds \"x\""), \
                mock.patch.object(tick, "sh") as sh:
            code, text = prune_act.act_on(str(self.main), "13", "remove", False)
        self.assertEqual(code, 0)
        self.assertIn("skipped remove 13", text)
        self.assertIn("draft", text)
        sh.assert_not_called()

    def test_the_cli_prints_the_dry_run(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(prune.shutil, "which", return_value="/bin/x"):
            self.assertEqual(prune.main(["remove", "13", "--repo", str(self.main), "--dry-run"]), 0)
        self.assertIn("would run hal2-cli-git worktree remove 13 --remote", out.getvalue())
        self.assertEqual(subprocess.run(["git", "worktree", "list"], cwd=self.main, capture_output=True,
                                        text=True).stdout.count("/13 "), 1)


class ActMarked(MarkedSlots):
    def setUp(self):
        super().setUp()
        live = mock.patch.object(prune_act, "live", return_value=({}, []))
        live.start()
        self.addCleanup(live.stop)
        # The host's own processes never decide a test: no build runs in a fixture's field.
        quiet = mock.patch.object(prune_proof, "build_running", return_value=False)
        quiet.start()
        self.addCleanup(quiet.stop)
        self.calls = []

    def sh(self, argv, cwd, timeout=900):
        self.calls.append(argv)
        if argv[0] == "hal2-cli-git":
            return 0, "removed"
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr).strip()

    def remote(self, name):
        return subprocess.run(["git", "ls-remote", "origin", f"refs/heads/{name}"], cwd=self.main,
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_remove_forces_the_worktree_then_deletes_origin_nn(self):
        self.assertTrue(self.remote("31"))
        with mock.patch.object(tick, "sh", side_effect=self.sh):
            code, text = prune_act.act_on(str(self.main), "31", "remove", False)
        self.assertEqual(code, 0, text)
        self.assertEqual(self.calls[0], ["hal2-cli-git", "worktree", "remove", "31", "--force"])
        self.assertEqual(self.calls[1], ["git", "push", "--quiet", "origin", "--delete", "31"])
        self.assertFalse(self.remote("31"))
        self.assertTrue(self.remote("02"))

    def test_remove_fetches_and_checks_again(self):
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", "-b", "31", str(self.tmp / "hal2.git"), str(other))
        git(other, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "--allow-empty", "-m", "late")
        git(other, "push", "-q", "origin", "31")
        with mock.patch.object(tick, "sh", side_effect=self.sh):
            code, text = prune_act.act_on(str(self.main), "31", "remove", False)
        self.assertEqual(code, 0)
        self.assertIn("skipped remove 31: origin/31: 1 commit(s) not in origin/02", text)
        self.assertEqual(self.calls, [])
        self.assertTrue(self.remote("31"))

    def test_kept_when_a_commit_is_not_in_the_leads_branch(self):
        with mock.patch.object(tick, "sh", side_effect=self.sh):
            code, text = prune_act.act_on(str(self.main), "32", "remove", False)
        self.assertIn("skipped remove 32", text)
        self.assertEqual(self.calls, [])

    def test_the_dry_run_names_both_commands(self):
        code, text = prune_act.act_on(str(self.main), "31", "remove", True)
        self.assertEqual(code, 0)
        self.assertEqual(text, "would run hal2-cli-git worktree remove 31 --force; then "
                               "git push --quiet origin --delete 31")



if __name__ == "__main__":
    unittest.main()
