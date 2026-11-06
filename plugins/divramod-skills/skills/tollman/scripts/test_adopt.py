"""A landing the train state does not know is adopted, never doubled (adopt.py; the user, 2026-11-04). Replays
train 51: `engine.py land` typed by hand pushed the train with no `started` line; the round's `restart` then failed
on the queue and its wake asked for a rerun. Now `restart` adopts the live landing (its pid, branch and start time
from the carrier's queue entry), the watch finds its run, and a hand-typed `engine.py land` is refused."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import adopt
import engine
import land_name
import train_state

os.environ.setdefault("HAL2_WORKQUEUE_FREEZE", "0")  # no test takes a real workqueue hold (plan 0466)

FIELD = "tollman-train-big-0514-0581-28"
ENTRY = {"slot": FIELD, "branch": FIELD, "pid": os.getpid(), "landing": "2026-11-04T11-51-10Z-x",
         "enqueued": "2026-11-04T11:51:10.004Z", "land_ref": None, "holding": True}


def queue_run(entry: dict | None, code: int = 0):
    """A fake `subprocess.run` answering `hal2-cli-git worktree queue --json` with `entry` in it."""
    body = json.dumps({"queue": [entry] if entry else []})
    return lambda *a, **k: SimpleNamespace(returncode=code, stdout=body, stderr="")


class Live(unittest.TestCase):
    def test_a_live_landing_of_the_carrier_is_found(self):
        with mock.patch.object(train_state, "command_of", return_value="hal2-cli-git worktree merge-to-main --json"):
            self.assertEqual(adopt.live("/x", FIELD, run=queue_run(ENTRY))["pid"], os.getpid())

    def test_merge_to_main_counts_as_a_live_landing_another_command_not(self):
        for command, want in (("hal2-cli-git worktree merge-to-main --json", True),
                              ("python3 /s/engine.py land --repo /t", True), ("vim notes.md", False)):
            with mock.patch.object(train_state, "command_of", return_value=command):
                self.assertEqual(train_state.alive(os.getpid()), want, command)

    def test_no_landing_a_dead_pid_another_slot_or_an_unreadable_queue_find_none(self):
        self.assertIsNone(adopt.live("/x", FIELD, run=queue_run({**ENTRY, "landing": None})))
        self.assertIsNone(adopt.live("/x", FIELD, run=queue_run({**ENTRY, "pid": 2 ** 22 + 7})))
        self.assertIsNone(adopt.live("/x", FIELD, run=queue_run({**ENTRY, "slot": "07"})))
        self.assertIsNone(adopt.live("/x", FIELD, run=queue_run(ENTRY, code=1)))
        self.assertIsNone(adopt.live("/x", FIELD, run=lambda *a, **k: (_ for _ in ()).throw(OSError("gone"))))


class Adopt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.main = self.tmp.name
        self.folder = mock.patch.object(train_state, "folder", lambda main: Path(self.main))
        self.folder.start()
        self.addCleanup(self.folder.stop)
        self.addCleanup(self.tmp.cleanup)
        cli = mock.patch.object(land_name, "cli", lambda args, cwd: (127, "no hal2-cli-git"))  # no real call
        cli.start()
        self.addCleanup(cli.stop)

    def adopt(self, entry, said):
        """adopt.adopt with `worktree land-ref` answering `said` ((code, text)); the started line."""
        with mock.patch.object(land_name, "cli", lambda args, cwd: said):
            code, text = adopt.adopt(self.main, FIELD, {"train": "t51"}, entry)
        return code, text, [r for r in train_state.lines(self.main) if r["kind"] == "started"][-1]

    def test_the_started_line_names_the_pid_the_branch_hal2_git_says_and_the_landings_start(self):
        said = (0, json.dumps({"schema": 1, "slot": FIELD, "kind": "train", "current": "land/train-51-2",
                               "next": "land/train-51-3"}))
        code, text, line = self.adopt(ENTRY, said)
        self.assertEqual((code, line["pid"], line["land_ref"], line["at"]),
                         (0, os.getpid(), "train-51-2", "2026-11-04T11:51:10Z"))
        self.assertIn("no second one started", text)
        self.assertIn("land/train-51-2", text)

    def test_a_branch_nobody_names_is_left_out_never_the_carriers_own_name(self):
        code, text, line = self.adopt(ENTRY, (1, "no numbered mark"))
        self.assertEqual((code, "land_ref" in line), (0, False))
        self.assertIn("its branch unknown", text)

    def test_an_earlier_starts_landing_log_is_moved_aside_so_its_status_is_not_this_trains(self):
        log = Path(self.main) / train_state.LOG
        log.write_text('{"status": "refused", "message": "train 50: refused"}\n')
        adopt.adopt(self.main, FIELD, {"train": "t51"}, ENTRY)
        self.assertIsNone(train_state.result(self.main))
        self.assertTrue(log.with_name(log.name + ".before-adopt").exists())

    def test_a_land_ref_on_the_entry_wins(self):
        for held in ("train-51-1", "land/train-51-1"):
            adopt.adopt(self.main, FIELD, {"train": "t51"}, {**ENTRY, "land_ref": held})
            self.assertEqual(train_state.lines(self.main)[-1]["land_ref"], "train-51-1")


class Restart(unittest.TestCase):
    def test_restart_adopts_instead_of_marking_or_spawning(self):
        train = {"train": "t51", "pid": None, "state": "formed", "cars": [], "starts": 0}
        with mock.patch.object(engine, "here", return_value=("/m", FIELD, train, "/top")), \
                mock.patch.object(engine.train_wt, "astray", return_value=None), \
                mock.patch.object(adopt, "live", return_value=ENTRY), \
                mock.patch.object(adopt, "adopt", return_value=(0, "adopted")) as adopted, \
                mock.patch.object(engine, "cli") as cli, mock.patch.object(engine, "spawn") as spawn:
            self.assertEqual(engine.restart("/top"), (0, "adopted"))
        adopted.assert_called_once()
        cli.assert_not_called()
        spawn.assert_not_called()


class Direct(unittest.TestCase):
    def test_only_the_spawned_child_may_land(self):
        self.assertTrue(adopt.direct({}))
        self.assertFalse(adopt.direct({adopt.SPAWNED: "1"}))

    def test_a_hand_typed_engine_land_is_refused_with_exit_2(self):
        env = {k: v for k, v in os.environ.items() if k != adopt.SPAWNED}
        p = subprocess.run([sys.executable, engine.__file__, "land", "--repo", tempfile.gettempdir()], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2)
        self.assertIn("engine.py restart", p.stderr)


if __name__ == "__main__":
    unittest.main()
