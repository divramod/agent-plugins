"""The prune round (hal2 plan 0534 step 2): fake fields in a tmp root, a fake disk and fake child processes; no real
sleep, no real du, nothing outside the tmp folder."""

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer
import prune_round as pr


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1.0
        return self.t


class Farm(unittest.TestCase):
    """~/a/hal2 (main) with fields 11 (busy), 12 (idle, 40 GB), 13 (idle, 90 GB), 14 (idle, target tracked) and a train."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        self.main = str(home / "a/hal2")
        root = home / ".hal/git/worktree/hal2"
        self.fields = {n: root / n for n in ("11", "12", "13", "14", "tollman-train-1")}
        for f in self.fields.values():
            (f / pr.TARGET).mkdir(parents=True)
            (f / pr.TARGET / "blob").write_text("x")
        self.sizes = {"11": 50, "12": 40, "13": 90, "14": 70, "tollman-train-1": 99}
        self.busy = {"11"}
        self.tracked = {"14"}
        self.base = 20.0
        self.p = [mock.patch.object(pr.mtm_scan, "worktrees", lambda m: [
                      {"path": str(f), "branch": n} for n, f in self.fields.items()]),
                  mock.patch.object(pr, "free_gb", self.free),
                  mock.patch.object(pr, "size_gb", lambda t: self.sizes[t.parent.parent.parent.name]),
                  mock.patch.object(pr, "is_idle", lambda f: f.name not in self.busy),
                  mock.patch.object(pr, "is_ignored", lambda f: f.name not in self.tracked),
                  mock.patch.object(pr, "is_checkout", lambda f: True)]  # the fake farm is no git repository
        out = contextlib.redirect_stdout(io.StringIO())
        out.__enter__()
        self.addCleanup(out.__exit__, None, None, None)
        for p in self.p:
            p.start()
            self.addCleanup(p.stop)

    def free(self):
        gone = sum(self.sizes[n] for n, f in self.fields.items() if not (f / pr.TARGET).exists())
        return self.base + gone

    def alive(self):
        return sorted(n for n, f in self.fields.items() if (f / pr.TARGET).exists())


class Disk(Farm):
    def test_nothing_is_deleted_while_the_disk_is_above_the_mark(self):
        self.base = 200.0
        self.assertEqual(pr.disk_step(self.main, 1e9), ["200 GB free, nothing to do"])
        self.assertEqual(len(self.alive()), 5)

    def test_an_idle_target_goes_biggest_first_only_while_under_the_mark_and_a_busy_one_stays(self):
        lines = pr.disk_step(self.main, 1e9)
        self.assertEqual(len(lines), 2, lines)  # 13 (90 GB) then 12 (40 GB): 20 + 130 = 150, stop
        self.assertTrue(lines[0].startswith("deleted hal2/13 ") and lines[1].startswith("deleted hal2/12 "))
        self.assertEqual(self.alive(), ["11", "14", "tollman-train-1"])
        self.assertTrue((self.fields["11"] / pr.TARGET / "blob").exists(), "busy: untouched")
        self.assertTrue((self.fields["14"] / pr.TARGET / "blob").exists(), "tracked target: untouched")

    def test_it_stops_as_soon_as_the_mark_is_reached(self):
        self.base = 70.0  # 13 alone frees 90 GB: 160
        self.assertEqual(len(pr.disk_step(self.main, 1e9)), 1)
        self.assertEqual(self.alive(), ["11", "12", "14", "tollman-train-1"])

    def test_every_field_busy_deletes_nothing(self):
        self.busy = {"11", "12", "13"}
        self.assertEqual(pr.disk_step(self.main, 1e9), [])
        self.assertEqual(len(self.alive()), 5)

    def test_a_train_worktree_is_never_a_candidate(self):
        self.assertNotIn(self.fields["tollman-train-1"], pr.candidates(self.main))

    def test_past_its_limit_the_step_reports_a_timeout_by_the_fake_clock(self):
        self.assertEqual(pr.run_disk(self.main, 900, Clock()), None)  # a second per call: well inside
        self.base = 20.0
        for f in self.fields.values():
            (f / pr.TARGET).mkdir(exist_ok=True)
        self.assertEqual(pr.run_disk(self.main, 2, Clock()), "disk timed out after 2 s")

    def test_a_target_that_will_not_go_is_a_failure(self):
        with mock.patch.object(pr.shutil, "rmtree"):
            why = pr.run_disk(self.main)
        self.assertIn("not fully deleted", why)


def done(code, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


class Round(Farm):
    def run_round(self, prune):
        with mock.patch.object(pr.subprocess, "run", mock.Mock(side_effect=prune)) as m, mock.patch.object(pr.mtm_scan, "main_checkout",
                                                                                   lambda r: self.main):
            self.base = 200.0  # the disk step has nothing to do
            code = pr.run(self.main)
        return code, m

    def test_both_steps_ran_exit_0_and_the_prune_run_names_the_farm(self):
        code, m = self.run_round(lambda *a, **k: done(0, "removed 31"))
        self.assertEqual(code, 0)
        argv = m.call_args.args[0]
        self.assertEqual(argv[-3:], ["run", "--repo", self.main])
        self.assertTrue(argv[1].endswith("actions/prune/scripts/prune.py"), argv)
        self.assertEqual(m.call_args.kwargs["timeout"], pr.PRUNE_LIMIT)

    def test_a_prune_failure_exits_1_with_the_reason(self):
        with mock.patch("builtins.print") as out:
            code, _ = self.run_round(lambda *a, **k: done(2, "", "boom"))
        self.assertEqual(code, 1)
        self.assertIn("prune round failed: prune exit 2: boom", out.call_args.args[0])

    def test_a_prune_timeout_exits_1_with_the_limit(self):
        def late(*a, **k):
            raise subprocess.TimeoutExpired("prune", k["timeout"])
        with mock.patch("builtins.print") as out:
            code, _ = self.run_round(late)
        self.assertEqual(code, 1)
        self.assertIn("prune timed out after 1500 s", out.call_args.args[0])

    def test_a_failed_disk_step_does_not_skip_the_prune_but_fails_the_round(self):
        with mock.patch.object(pr, "disk_step", side_effect=RuntimeError("x")), \
                mock.patch.object(pr.subprocess, "run", return_value=done(0)) as m, \
                mock.patch.object(pr.mtm_scan, "main_checkout", lambda r: self.main), \
                mock.patch("builtins.print") as out:
            self.assertEqual(pr.run(self.main), 1)
        self.assertEqual(m.call_count, 1, "prune still ran")
        self.assertIn("prune round failed: disk failed: x", out.call_args.args[0])

    def test_the_farmer_command_runs_the_round(self):
        with mock.patch.object(pr, "run", return_value=1) as m:
            self.assertEqual(farmer.main(["prune-round", "--repo", "/x/farmer"]), 1)
        m.assert_called_once_with("/x/farmer")


if __name__ == "__main__":
    unittest.main()
