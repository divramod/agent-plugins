"""A field above 09 after the barn (hal2 plan 0360 step 7, D8; prune_act.py): removed only through the proof of
never-delete-unsaved-work. Replays of a field 12: with an unpushed commit it is refused (nothing stopped, nothing
removed); clean, its resting session is stopped by signal and it is removed with its remote branch. The session stop
and hal2-cli-git are fakes that record their calls."""

import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import prune_act
import tick
import worktree_farm
from test_farmer import git


class Field12(worktree_farm.Slots):
    def setUp(self):
        super().setUp()
        self.field = self.base / "12"
        git(self.main, "worktree", "add", "-q", "-b", "12", str(self.field), "origin/main")
        git(self.field, "push", "-q", "-u", "origin", "12")
        agent = {"pane_id": "%12", "checkout": str(self.field), "state": "idle", "since": 0}
        self.stops, self.calls = [], []
        for p in (mock.patch.object(prune_act, "live", return_value=({}, [agent])),
                  mock.patch.object(prune_act, "stop", side_effect=lambda main, pane: self.stops.append(pane)),
                  mock.patch.object(tick, "sh", side_effect=lambda argv, cwd, timeout=900:
                                    self.calls.append(argv) or (0, "removed"))):
            p.start()
            self.addCleanup(p.stop)

    def test_an_unpushed_commit_refuses_the_removal(self):
        git(self.field, "commit", "-q", "--allow-empty", "-m", "not pushed")
        code, text = prune_act.act_on(str(self.main), "12", "remove", False)
        self.assertEqual(code, 0)
        self.assertEqual(text, "skipped remove 12: 1 commit(s) not on origin/main")
        self.assertEqual((self.stops, self.calls), ([], []), "nothing stopped, nothing removed")
        self.assertTrue(self.field.is_dir())

    def test_a_clean_field_is_stopped_by_signal_and_removed_with_its_remote_branch(self):
        code, text = prune_act.act_on(str(self.main), "12", "remove", False)
        self.assertEqual((code, text), (0, "removed"))
        self.assertEqual(self.stops, ["%12"])
        self.assertEqual(self.calls, [["hal2-cli-git", "worktree", "remove", "12", "--remote"]])


if __name__ == "__main__":
    unittest.main()
