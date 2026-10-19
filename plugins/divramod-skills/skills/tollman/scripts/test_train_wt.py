"""Hal2 plan 0375 D5: a train's own worktree `tollman-train-<plan>-...` (train_wt.py), its name, and its drop only
through the never-delete-unsaved-work proof. A temporary repository (origin, the yard, the tollman's field), never the
user's; the train's landing is never started."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import pretest_train
import train_wt


def git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Name(unittest.TestCase):
    def test_the_cars_plan_numbers_in_order_else_the_field(self):
        cars = [{"field": "07", "plan": "0375-tollman-switch"}, {"field": "09", "plan": "0365-queue-view"},
                {"field": "11", "plan": ""}, {"field": "12", "plan": "tollman/3/a-shot"}]
        self.assertEqual(train_wt.name(cars), "tollman-train-0375-0365-f11-f12")
        self.assertTrue(train_wt.is_train("tollman-train-0375") and not train_wt.is_train("tollman-hal2"))
        self.assertTrue(train_wt.ours(None, "tollman-hal2") and train_wt.ours("tollman-train-f07", "tollman-hal2"))
        self.assertFalse(train_wt.ours("02", "tollman-hal2"), "another field's carrier")


class Drop(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        origin, self.main = self.tmp / "origin.git", self.tmp / "hal2"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.tmp, "clone", "-q", str(origin), str(self.main))
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
            git(self.main, "config", k, v)
        self.commit(self.main, "a.txt")
        git(self.main, "push", "-q", "origin", "HEAD:main")
        fields = self.tmp / "worktree"
        self.field = fields / "tollman-hal2"
        git(self.main, "worktree", "add", "-q", "-b", "tollman-hal2", str(self.field))
        self.car = fields / "07"
        git(self.main, "worktree", "add", "-q", "-b", "07", str(self.car))
        self.commit(self.car, "seven.txt")
        git(self.car, "push", "-q", "origin", "07")
        self.cars = [{"field": "07", "plan": "0375-tollman-switch"}]

    def commit(self, cwd, name):
        (Path(cwd) / name).write_text(name)
        git(cwd, "add", name)
        git(cwd, "commit", "-qm", name)

    def train(self) -> Path:
        code, wt = train_wt.add(str(self.field), self.cars)
        self.assertEqual(code, 0, wt)
        git(wt, "merge", "-q", "--no-ff", "-m", "Merge branch '07'", "07")
        return Path(wt)

    def test_a_train_of_merges_is_dropped_with_its_branch(self):
        wt = self.train()
        self.assertEqual((wt.name, wt.parent, git(wt, "branch", "--show-current")),
                         ("tollman-train-0375", self.field.parent, "tollman-train-0375"))
        (wt / "plans").mkdir()
        (wt / "plans/CURRENT_PLAN").write_text("0375-tollman-switch\n")  # the train's title, no car's work
        self.assertEqual(train_wt.drop(str(wt)), (0, "worktree tollman-train-0375 dropped"))
        self.assertEqual((wt.exists(), git(self.main, "branch", "--list", wt.name)), (False, ""))
        self.assertEqual(train_wt.drop(str(wt))[0], 0, "gone already")

    def test_unsaved_work_keeps_the_worktree(self):
        wt = self.train()
        (wt / "a.txt").write_text("changed")
        code, text = train_wt.drop(str(wt))
        self.assertEqual(code, 1)
        self.assertIn("kept (never delete unsaved work): 1 uncommitted change(s)", text)
        git(wt, "commit", "-qam", "a hand's commit")
        code, text = train_wt.drop(str(wt))
        self.assertEqual(code, 1)
        self.assertIn("1 commit(s) of no train and on no other origin branch", text)
        self.assertTrue(wt.is_dir())
        code, text = train_wt.add(str(self.field), self.cars)
        self.assertEqual(code, 1, "the same train's name is taken by unsaved work: no train forms")
        self.assertIn("left from before", text)
        git(wt, "reset", "-q", "--hard", "HEAD^")
        self.assertEqual(train_wt.add(str(self.field), self.cars), (0, str(wt)), "a clean leftover goes first")

    def test_only_a_train_s_worktree_is_ever_dropped(self):
        self.assertEqual(train_wt.drop(str(self.car))[0], 1)
        self.assertTrue(self.car.is_dir())
        stray = self.field.parent / "tollman-train-f99"
        stray.mkdir()
        self.assertIn("is no worktree of its own", train_wt.drop(str(stray))[1])

    def test_the_landing_stamps_its_own_pid_on_the_mark(self):
        wt, calls = self.train(), []
        with mock.patch.object(engine, "cli", lambda args, cwd: calls.append(args) or (0, "{}")), \
                mock.patch.object(pretest_train, "before_landing", return_value=True), \
                mock.patch("sys.stdout"):
            self.assertEqual(engine.land(str(wt)), 1, "a red pretest starts no landing")
        self.assertEqual(calls, [["worktree", "queue", "train", wt.name, "--pid", str(os.getpid()), "--json"]],
                         "the sleep stops the train's process group by it (plan 0375 D2)")


if __name__ == "__main__":
    unittest.main()
