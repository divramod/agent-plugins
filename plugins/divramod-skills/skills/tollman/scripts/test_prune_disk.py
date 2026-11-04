"""The prune duty's disk phase (prune_disk.py; hal2 plan 0514 step 7, D18): asked of /prune as a program every round,
started detached when the disk is below /prune's mark, never held back by a workqueue hold, a train's local phase or
a running prune run. No real /prune or process is started: the ask and the spawn are fakes."""

import contextlib
import datetime as dt
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import prune
import prune_disk
import tick

NOW = dt.datetime(2026, 10, 31, 20, 0)
DUE = {"due": True, "free_gb": 61.5, "below_gb": 80, "until_gb": 150, "note": None}


def answer(out: str, code: int = 0):
    return lambda argv, **kw: subprocess.CompletedProcess(argv, code, out, "boom" if code else "")


class Disk(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.main = str(self.tmp / "hal2")
        Path(self.main).mkdir()
        (self.tmp / "state").mkdir()
        for p in (mock.patch.object(prune_disk, "folder", return_value=self.tmp / "state"),
                  mock.patch.object(prune_disk, "script", return_value=self.tmp / "prune/scripts/prune.py")):
            p.start()
            self.addCleanup(p.stop)

    def ctx(self, **more):
        return {"main": self.main, "top": "/x/tollman-hal2", "now": NOW, "log": [], **more}

    def test_due_is_asked_of_prune_as_a_program(self):
        seen = []

        def run(argv, **kw):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps(DUE), "")
        self.assertEqual(prune_disk.due(self.main, run), (DUE, ""))
        self.assertEqual(seen[0][1:], [str(self.tmp / "prune/scripts/prune.py"), "disk", "--due", "--json", "--repo",
                                       self.main])
        self.assertIn("exited 1: boom", prune_disk.due(self.main, answer("", 1))[1])
        self.assertIsNone(prune_disk.due(self.main, answer("not json"))[0])

    def test_below_the_mark_starts_the_phase_detached_above_it_nothing(self):
        got = prune_disk.actions(self.ctx(), ask=lambda m: (DUE, ""))
        self.assertEqual([(a["kind"], a["do"], a["key"]) for a in got], [("disk-phase", "run", "prune:disk-phase")])
        self.assertEqual(got[0]["argv"][1:], [str(Path(prune_disk.__file__).resolve()), "start", "--repo", self.main])
        self.assertIn("61.5 GB free, below 80 GB", got[0]["text"])
        self.assertEqual(prune_disk.actions(self.ctx(), ask=lambda m: ({**DUE, "due": False}, "")), [])

    def test_a_failed_ask_wakes_once_per_6_hours(self):
        got = prune_disk.actions(self.ctx(), ask=lambda m: (None, "prune.py disk --due exited 2"))
        self.assertEqual([(a["kind"], a["do"]) for a in got], [("disk-failed", "wake")])
        later = [{"at": (NOW - dt.timedelta(hours=1)).isoformat(), "key": got[0]["key"]}]
        self.assertEqual(tick.fresh(got, later, NOW), [])

    def test_a_started_phase_is_not_started_twice_and_comes_again_after_its_window(self):
        a = prune_disk.actions(self.ctx(), ask=lambda m: (DUE, ""))
        five = [{"at": (NOW - dt.timedelta(minutes=5)).isoformat(), "key": "prune:disk-phase"}]
        eleven = [{"at": (NOW - dt.timedelta(minutes=11)).isoformat(), "key": "prune:disk-phase"}]
        self.assertEqual(tick.fresh(a, five, NOW), [])
        self.assertEqual(len(tick.fresh(a, eleven, NOW)), 1)
        (self.tmp / "state" / prune_disk.DISK_FILE).write_text(json.dumps({"pid": os.getpid(), "at": time.time()}))
        ask = mock.Mock()
        self.assertEqual(prune_disk.actions(self.ctx(), ask=ask), [])  # a live phase: not even asked
        ask.assert_not_called()

    def test_never_held_back_by_a_hold_a_train_or_a_running_prune_run(self):
        """D18: the duty's handler plans the disk phase while a workqueue hold stands and a /prune run lives."""
        with mock.patch.object(prune_disk, "due", return_value=(DUE, "")), \
                mock.patch.object(prune, "held", return_value="deferred: train building (hold h1 of field hal2/31)"), \
                mock.patch.object(prune, "running", return_value=True), \
                mock.patch("train_wt.retry", return_value=[]):
            got = prune.handler({}, self.ctx())
        self.assertEqual([(a["kind"], a["do"]) for a in got], [("disk-phase", "run")])

    def test_start_spawns_prunes_disk_detached_once(self):
        spawned = []

        def spawn(argv, **kw):
            spawned.append((argv, kw))
            return mock.Mock(pid=os.getpid())  # a live pid: the next start sees it running
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(prune_disk.start(self.main, spawn), 0)
            self.assertEqual(prune_disk.start(self.main, spawn), 0)
        self.assertEqual(len(spawned), 1)
        argv, kw = spawned[0]
        self.assertEqual(argv[1:], [str(self.tmp / "prune/scripts/prune.py"), "disk", "--repo", self.main])
        self.assertTrue(kw["start_new_session"])
        self.assertIn("disk phase already going", out.getvalue())
        self.assertEqual(json.loads((self.tmp / "state" / prune_disk.DISK_FILE).read_text())["argv"], argv)


if __name__ == "__main__":
    unittest.main()
