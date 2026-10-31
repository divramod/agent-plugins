"""L52, L69 of the tollman: a stale index.lock in the role's worktree is removed before the merge from main."""

import os
import tempfile
import time
import unittest
from pathlib import Path

import stale_lock


def answers(lsof_lock="", git_pids="", cwds=""):
    def sh(argv):
        if argv[:2] == ["lsof", "-t"]:
            return lsof_lock
        if argv[0] == "pgrep":
            return git_pids
        return cwds
    return sh


class StaleLock(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.top, self.gd = self.tmp / "tollman-hal2", self.tmp / "hal2/.git/worktrees/tollman-hal2"
        self.top.mkdir()
        self.gd.mkdir(parents=True)
        (self.top / ".git").write_text(f"gitdir: {self.gd}\n")
        self.lock = self.gd / "index.lock"
        self.lock.write_text("")
        old = time.time() - 11 * 60
        os.utime(self.lock, (old, old))

    def test_an_old_lock_nobody_holds_is_removed_and_named(self):
        note = stale_lock.clear(str(self.top), sh=answers())
        self.assertIn("index.lock", note)
        self.assertFalse(self.lock.exists())

    def test_a_young_held_or_worked_on_lock_stays(self):
        os.utime(self.lock, None)
        self.assertIsNone(stale_lock.clear(str(self.top), sh=answers()), "younger than 10 min")
        os.utime(self.lock, (time.time() - 3600, time.time() - 3600))
        self.assertIsNone(stale_lock.clear(str(self.top), sh=answers(lsof_lock="123\n")), "a holder")
        busy = answers(git_pids="77\n", cwds=f"p77\nn{self.top.resolve()}/code\n")
        self.assertIsNone(stale_lock.clear(str(self.top), sh=busy), "a git process works in the field")
        self.assertIsNone(stale_lock.clear(str(self.top), sh=lambda argv: None), "lsof missing: kept")
        self.assertTrue(self.lock.exists())
        elsewhere = answers(git_pids="77\n", cwds="p77\nn/somewhere/else\n")
        self.assertIsNotNone(stale_lock.clear(str(self.top), sh=elsewhere), "git elsewhere is no reason")

    def test_no_lock_costs_nothing(self):
        self.lock.unlink()
        self.assertIsNone(stale_lock.clear(str(self.top), sh=lambda argv: self.fail("no command without a lock")))


if __name__ == "__main__":
    unittest.main()
