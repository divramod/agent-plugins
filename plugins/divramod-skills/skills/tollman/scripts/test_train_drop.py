"""Hal2 plan 0490 row 18 (L135, the tollman's learning landed-blocks-on-worktree-remove): after train 28 landed,
`engine.py landed` removed the train's worktree (a full build tree) for 6+ min inside the round and train 29 did not
form. Now the next train forms first and the old worktree is dropped after, detached (train_wt.later), retried by
the prune duty; and a round's failed import of a duty's module is tried once more (handlers.load). On
engine_farm.py's farm: no landing is ever started, no real queue."""

import fcntl
import importlib
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import handlers
import prune
import train_state
import train_wt
from engine_farm import Farm


class NextFirst(Farm):
    def setUp(self):
        super().setUp()
        self.crop("07", {"seven.txt": "7"}, plan="0294-tollman-role")
        self.crop("09", {"nine.txt": "9"})
        self.round()
        self.alive.add(40001)
        self.old = self.wm.parent / self.carrier()

    def test_l135_the_next_train_forms_before_the_landed_train_s_worktree_is_dropped(self):
        self.ends({"status": "landed", "commit": "c0ffee", "run": "https://github.com/x/runs/9"}, land=True)
        self.crop("11", {"eleven.txt": "11"})  # hitched while the train of 07 and 09 landed
        seen, run = [], self.detach

        def detach(argv, **kw):  # the drop run's start: what stands by then
            seen.append((self.state()[-3:], self.old.is_dir()))
            run(argv, **kw)
        with mock.patch.object(train_wt, "DETACH", detach):
            self.round()
        new = self.carrier()
        self.assertEqual(self.last, [("landed", "run", "-"), ("in-the-barn", "relay", "07"),
                                     ("in-the-barn", "relay", "09"), ("chain", "run", "-")])
        self.assertEqual(seen, [([("landed", self.old.name), ("formed", new), ("started", new)], True)],
                         "the drop starts once the next train formed and started, the landed one's worktree still there")
        self.assertFalse(self.old.exists(), "then it is dropped, through the proof")
        self.assertTrue((self.wm.parent / new).is_dir(), "the standing train's worktree is never dropped")
        log = (self.wm_state / train_wt.DROP_LOG).read_text()
        self.assertIn(f"worktree {self.old.name} dropped", log)

    def test_landed_itself_drops_nothing_and_later_never_waits_for_the_drop(self):
        self.ends({"status": "landed", "commit": "c0ffee"}, land=True)
        with mock.patch.object(train_wt, "drop", side_effect=AssertionError("no drop inside the round")):
            code, text = engine.landed(str(self.old))
        self.assertEqual(code, 0, text)
        self.assertTrue(self.old.is_dir(), "landed leaves the worktree to the drop run")
        popen = mock.Mock()  # a slow drop: the process is started, never waited for
        with mock.patch.object(train_wt, "DETACH", popen), \
                mock.patch.object(train_wt, "drop", side_effect=AssertionError("never in later's process")):
            self.assertEqual(train_wt.later(str(self.wm)), f"dropping in the background: {self.old.name}")
        argv, kw = popen.call_args.args[0], popen.call_args.kwargs
        self.assertEqual((argv[2:5], kw["start_new_session"], kw["cwd"]), (["drop-left", "--repo", str(self.wm)],
                                                                           True, str(self.wm)))
        self.assertEqual(popen.return_value.method_calls, [], "no wait, no communicate")

    def test_the_drop_run_skips_the_standing_train_a_newer_worktree_and_a_busy_lock(self):
        self.assertEqual(train_wt.drop_left(str(self.wm), time.time()), [], "only the standing train: none left")
        before = time.time() - 60
        code, stray = train_wt.add(str(self.wm), [{"field": "77", "plan": ""}])  # made after `before`
        self.assertEqual(code, 0, stray)
        self.assertEqual(train_wt.drop_left(str(self.wm), before), [], "made after the run started: a train forming")
        with (train_state.folder(str(self.main)) / train_wt.DROP_LOCK).open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assertEqual(train_wt.drop_left(str(self.wm), time.time()), ["another drop run goes on"])
        (done,) = train_wt.drop_left(str(self.wm), time.time())
        self.assertIn("worktree tollman-train-f77 dropped", done)
        self.assertTrue(self.old.is_dir(), "the standing train's worktree stays")

    def test_the_prune_duty_retries_a_left_worktree(self):
        top, main = str(self.wm), str(self.main)
        self.assertEqual(train_wt.retry(top, main), [], "only the standing train's worktree")
        train_wt.add(top, [{"field": "77", "plan": ""}])
        ctx = {"main": main, "top": top, "now": None, "log": []}
        with mock.patch.object(prune, "plan", return_value=[]):
            (a,) = prune.handler({}, ctx)
        self.assertEqual((a["duty"], a["kind"], a["do"], a["key"], a["window"]),
                         ("prune", "train-drop", "run", "train-drop:tollman-train-f77", train_wt.RETRY))
        self.assertEqual(a["argv"][2:], ["later", "--repo", top])


class ImportRetry(unittest.TestCase):
    """L135: `AttributeError: module 'mtm_scan' has no attribute 'QUEUE'` at trains.py's import, once, while the
    yard's files were half updated: the old mtm_scan was loaded, the new trains.py read it."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        sys.path.insert(0, str(self.dir))
        self.addCleanup(sys.path.remove, str(self.dir))
        for name in ("dep_l135", "user_l135"):
            self.addCleanup(sys.modules.pop, name, None)
        (self.dir / "dep_l135.py").write_text("OLD = 1\n")
        (self.dir / "user_l135.py").write_text("import dep_l135\nQUEUE = dep_l135.QUEUE\n\ndef handler(item, ctx):\n"
                                               "    return [QUEUE]\n")
        importlib.invalidate_caches()
        importlib.import_module("dep_l135")  # the old one, loaded before the update

    def updated(self, seconds):
        (self.dir / "dep_l135.py").write_text("OLD = 1\nQUEUE = ['hal2-cli-git', 'worktree', 'queue']\n")

    def test_a_failed_import_is_retried_once_after_a_pause_with_the_named_module_reloaded(self):
        with mock.patch.object(handlers.time, "sleep", side_effect=self.updated) as pause, mock.patch("sys.stderr"):
            item = handlers.Handlers({"duty:x": "user_l135.handler"})["duty:x"]
        self.assertEqual(item({}, {}), [["hal2-cli-git", "worktree", "queue"]])
        pause.assert_called_once_with(handlers.PAUSE)

    def test_a_second_failure_is_loud(self):
        with mock.patch.object(handlers.time, "sleep") as pause, mock.patch("sys.stderr"), \
                self.assertRaisesRegex(AttributeError, "QUEUE"):
            handlers.load("user_l135")
        pause.assert_called_once_with(handlers.PAUSE)


if __name__ == "__main__":
    unittest.main()
