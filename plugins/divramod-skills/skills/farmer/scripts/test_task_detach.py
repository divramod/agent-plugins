import datetime as dt
import json
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import task_detach as td
import tasks
import tick

NOW = 1_790_000_000.0
KEYS = {"schema", "task", "state", "pid", "started", "ended", "limit", "cmds", "top", "main", "exit", "output", "consumed"}


class Files(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name) / "tasks"
        self.spawned = []

    def start(self, **kw):
        return td.start(self.folder, "prune round", ["farmer prune-round"], "/x/farmer", "/x/hal2", 2700, NOW,
                        spawn=lambda argv, **k: self.spawned.append((argv, k)), **kw)

    def test_the_result_has_a_pinned_shape_and_is_written_atomically(self):
        rec = self.start()
        on_disk = json.loads((self.folder / "prune-round.json").read_text())
        self.assertEqual(set(on_disk), KEYS)
        self.assertEqual((on_disk["schema"], on_disk["state"], on_disk["limit"], on_disk["consumed"]), (1, "starting", 2700, False))
        self.assertEqual(rec["started"], td.stamp(NOW))
        self.assertEqual([p.name for p in self.folder.iterdir()], ["prune-round.json"])  # no temp file left

    def test_the_runner_is_started_detached_in_its_own_session(self):
        self.start()
        argv, kw = self.spawned[0]
        self.assertEqual(argv[1:3], [str(Path(td.__file__).resolve()), "run"])
        self.assertTrue(kw.get("start_new_session") or kw.get("creationflags") is not None)
        self.assertEqual(kw["cwd"], "/x/hal2")

    def test_a_runner_that_cannot_start_leaves_a_failed_result(self):
        def boom(argv, **kw):
            raise OSError("no such interpreter")
        td.start(self.folder, "prune round", ["x"], "/t", "/m", 300, NOW, spawn=boom)
        rec = td.read(self.folder, "prune round")
        self.assertEqual((rec["state"], rec["exit"], td.status(rec, NOW, lambda p: True)), ("done", 1, "finished"))
        self.assertIn("no such interpreter", rec["output"])

    def test_the_runner_runs_the_check_with_the_limit_and_writes_the_result(self):
        self.start()
        import tasks
        with mock.patch.object(tasks, "run_check", return_value=(False, "farmer prune-round: exit 1\nboom")) as chk:
            self.assertEqual(td.run(self.folder / "prune-round.json"), 0)
        chk.assert_called_once_with(["farmer prune-round"], "/x/farmer", "/x/hal2", 2700)
        rec = td.read(self.folder, "prune round")
        self.assertEqual((rec["state"], rec["exit"], rec["output"], rec["consumed"]), ("done", 1, "farmer prune-round: exit 1\nboom", False))
        self.assertGreater(rec["pid"], 0)

    def test_a_crashing_check_is_a_failed_result_not_a_hang(self):
        self.start()
        import tasks
        with mock.patch.object(tasks, "run_check", side_effect=RuntimeError("bad")):
            td.run(self.folder / "prune-round.json")
        rec = td.read(self.folder, "prune round")
        self.assertEqual((rec["state"], rec["exit"]), ("done", 1))
        self.assertIn("RuntimeError: bad", rec["output"])

    def test_status_by_state_age_and_pid(self):
        rec = {"state": "running", "pid": 7, "started": td.stamp(NOW), "limit": 100, "consumed": False}
        up, down = (lambda p: True), (lambda p: False)
        self.assertEqual([td.status(None, NOW), td.status(rec, NOW + 100, up), td.status(rec, NOW + 101, up),
                          td.status(rec, NOW + 5, down), td.status({**rec, "pid": 0}, NOW + 5, down)],
                         ["none", "running", "overdue", "dead", "running"])
        done = {**rec, "state": "done"}
        self.assertEqual([td.status(done, NOW), td.status({**done, "consumed": True}, NOW)], ["finished", "consumed"])

    def test_an_unreadable_or_foreign_result_is_none(self):
        self.folder.mkdir(parents=True)
        (self.folder / "a.json").write_text("{not json")
        (self.folder / "b.json").write_text('{"schema": 2}')
        self.assertEqual([td.read(self.folder, "a"), td.read(self.folder, "b"), td.read(self.folder, "c")], [None] * 3)


class Terminate(unittest.TestCase):
    def test_the_group_gets_sigterm_then_sigkill_after_the_grace_without_a_real_sleep(self):
        sleeps = []
        with mock.patch("os.killpg") as kill:
            td.terminate(4242, is_alive=lambda p: True, sleep=sleeps.append, grace=0.3)
        self.assertEqual([c.args for c in kill.call_args_list], [(4242, signal.SIGTERM), (4242, signal.SIGKILL)])
        self.assertEqual(len(sleeps), 3)

    def test_a_group_that_ended_on_sigterm_still_gets_the_sweep_and_none_before_start(self):
        with mock.patch("os.killpg") as kill:
            td.terminate(4242, is_alive=lambda p: False, sleep=lambda s: None)
            td.terminate(0)
        self.assertEqual(kill.call_count, 2)  # TERM + the sweep for the group's stragglers; pid 0 never signalled

    def test_a_gone_group_is_fine(self):
        with mock.patch("os.killpg", side_effect=ProcessLookupError):
            td.terminate(4242, is_alive=lambda p: False, sleep=lambda s: None)


# A farmer that fails as the prune round did: its --repo must be a git checkout (prune's first fact call).
STUB = (
    "import subprocess, sys\n"
    "repo = sys.argv[sys.argv.index('--repo') + 1]\n"
    "ok = subprocess.run(['git', '-C', repo, 'rev-parse', '--git-dir'], capture_output=True).returncode == 0\n"
    "print('ran in the farm' if ok else 'prune: git worktree list --porcelain gave no worktrees')\n"
    "sys.exit(0 if ok else 1)\n")


class Cause(unittest.TestCase):
    """Plan 0534 step 6: the detached runner passed `--repo <the ROLE.md's folder>` to `farmer prune-round`; outside
    git that folder is no farm and the round failed in 1-2 s with "no worktrees"."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.top, self.farm = self.root / "role-folder", self.root / "farm"
        self.top.mkdir()
        subprocess.run(["git", "init", "-q", str(self.farm)], check=True)
        (self.root / "farmer.py").write_text(STUB)
        patch = mock.patch.object(tasks, "FARMER", [sys.executable, str(self.root / "farmer.py")])
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_farm_commands_get_the_main_checkout_the_others_the_role_folder(self):
        self.assertEqual(tasks.argv("farmer prune-round", "/x/role", "/x/farm")[-2:], ["--repo", "/x/farm"])
        self.assertEqual(tasks.argv("farmer check flaky", "/x/role", "/x/farm")[-2:], ["--repo", "/x/role"])
        self.assertEqual(tasks.argv("farmer prune-round", "/x/role")[-2:], ["--repo", "/x/role"])
        self.assertEqual(tasks.argv("echo hi", "/x/role", "/x/farm"), ["sh", "-c", "echo hi"])

    def test_the_detached_runner_prunes_the_farm_not_the_folder_of_the_role_file(self):
        folder = self.root / "tasks"
        td.start(folder, "prune round", ["farmer prune-round"], str(self.top), str(self.farm), 2700, NOW,
                 spawn=lambda *a, **k: None)
        self.assertEqual(td.run(folder / "prune-round.json"), 0)
        rec = td.read(folder, "prune round")
        self.assertEqual((rec["exit"], rec["output"]), (0, ""))  # before the fix: exit 1, "gave no worktrees"

    def test_the_round_names_a_folder_that_is_no_checkout_at_once(self):
        import prune_round
        with mock.patch("sys.stdout") as out:
            self.assertEqual(prune_round.run(str(self.top)), 1)
        self.assertIn("is no git checkout", "".join(c.args[0] for c in out.write.call_args_list))


ROLE = """---
notify: never
---
## Tasks

### prune round

- **Cron**: `0 * * * *`
- **Limit**: 2700 s
- **Check**: `farmer prune-round`
- **Act**: notify
"""
T0 = dt.datetime(2026, 10, 31, 12, 0)


class Cadence(unittest.TestCase):
    """A failed detached task runs again only when the task is due again, and notifies once per window."""

    def test_a_task_not_due_is_not_planned_so_a_failed_result_is_not_restarted_between_its_crons(self):
        with tempfile.TemporaryDirectory() as top:
            role = Path(top) / "roles/farmer/ROLE.md"
            role.parent.mkdir(parents=True)
            role.write_text(ROLE)
            last = {"task:prune round": T0 + dt.timedelta(minutes=2)}  # ran at 12:02, after the 12:00 fire
            with mock.patch("due.last_runs", return_value=last):
                for minute in (5, 30, 59):
                    rows = tick.due_items(top, T0 + dt.timedelta(minutes=minute))[0]
                    self.assertEqual(rows, [], f"12:{minute:02}")
                self.assertEqual([r["name"] for r in tick.due_items(top, T0 + dt.timedelta(hours=1, minutes=1))[0]],
                                 ["task:prune round"])

    def test_the_notify_of_a_failed_run_is_dropped_again_within_its_hour(self):
        failed = tasks.outcome("notify", "prune round", "farmer prune-round: exit 1\nboom")
        log = [{"key": failed["key"], "at": T0.isoformat()}]
        for minutes, kept in ((5, 0), (59, 0), (61, 1)):
            now = T0 + dt.timedelta(minutes=minutes)
            self.assertEqual(len(tick.fresh([failed], log, now)), kept, f"{minutes} min later")


if __name__ == "__main__":
    unittest.main()
