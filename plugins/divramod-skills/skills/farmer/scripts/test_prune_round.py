"""The prune round (hal2 plan 0534 step 2): fake fields in a tmp root, a fake disk and fake child processes; no real
sleep, no real du, nothing outside the tmp folder."""

import contextlib
import io
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
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
                  mock.patch.object(pr, "is_checkout", lambda f: True),  # the fake farm is no git repository
                  mock.patch.object(pr, "autopilot", lambda m: self.autopilot),
                  mock.patch.object(pr, "record", self.record)]
        self.autopilot = None  # unreadable: the round runs by its cron, as before step 27
        self.recorded = []
        out = contextlib.redirect_stdout(io.StringIO())
        out.__enter__()
        self.addCleanup(out.__exit__, None, None, None)
        for p in self.p:
            p.start()
            self.addCleanup(p.stop)

    def record(self, main, started):
        self.recorded.append((main, started))
        return None

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


NOON = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def farm(**kw):
    return {"auto_prune": True, "prune_interval_s": 1200, "prune_due": None, "pruned_at": None, **kw}


class Due(unittest.TestCase):
    """The autopilot's switch (plan 0543 step 27): Prune now always, else auto prune by its interval."""

    def test_a_prune_now_runs_also_with_auto_prune_off_and_inside_the_interval(self):
        go, why = pr.due(farm(auto_prune=False, prune_due="2026-11-03T11:59:00Z", pruned_at="2026-11-03T11:58:00Z"), NOON)
        self.assertTrue(go)
        self.assertIn("Prune now asked at 2026-11-03T11:59:00Z", why)

    def test_auto_prune_off_without_a_prune_now_waits(self):
        self.assertEqual(pr.due(farm(auto_prune=False), NOON), (False, "auto prune off, no Prune now asked"))

    def test_the_interval_counts_from_the_last_passed_round(self):
        self.assertFalse(pr.due(farm(pruned_at="2026-11-03T11:45:00Z"), NOON)[0], "15 min of 20")
        self.assertTrue(pr.due(farm(pruned_at="2026-11-03T11:40:00Z"), NOON)[0], "20 min")
        self.assertTrue(pr.due(farm(), NOON)[0], "never ran")
        self.assertTrue(pr.due(farm(pruned_at="garbage"), NOON)[0], "unreadable: run")


class Gated(Farm):
    def round(self, code=0):
        with mock.patch.object(pr.subprocess, "run", return_value=done(code)) as m, \
                mock.patch.object(pr.mtm_scan, "main_checkout", lambda r: self.main):
            self.base = 200.0
            got = pr.run(self.main, now=lambda: NOON)
        return got, m

    def test_not_due_runs_nothing_and_records_nothing(self):
        self.autopilot = farm(auto_prune=False)
        code, m = self.round()
        self.assertEqual((code, m.call_count, self.recorded), (0, 0, []))

    def test_a_prune_now_runs_the_round_and_records_its_start(self):
        self.autopilot = farm(auto_prune=False, prune_due="2026-11-03T11:59:00Z")
        code, m = self.round()
        self.assertEqual((code, m.call_count), (0, 1))
        self.assertEqual(self.recorded, [(self.main, "2026-11-03T12:00:00Z")])

    def test_a_failed_round_is_not_recorded_so_the_prune_now_stays(self):
        self.autopilot = farm(prune_due="2026-11-03T11:59:00Z")
        self.assertEqual(self.round(code=2)[0], 1)
        self.assertEqual(self.recorded, [])

    def test_an_unreadable_autopilot_runs_by_the_cron_and_records_nothing(self):
        code, m = self.round()
        self.assertEqual((code, m.call_count, self.recorded), (0, 1, []))

    def test_a_failed_record_fails_the_round(self):
        self.autopilot = farm()
        with mock.patch.object(pr, "record", return_value="record exit 2: x"), mock.patch("builtins.print") as out:
            self.assertEqual(self.round()[0], 1)
        self.assertIn("prune round failed: record exit 2: x", out.call_args.args[0])


class Reads(unittest.TestCase):
    """The CLI calls themselves, by a fake bounded.run."""

    def test_show_is_read_in_the_main_checkout_and_a_bad_answer_is_none(self):
        with mock.patch.object(pr.bounded, "run", return_value=done(0, '{"farm": {"auto_prune": true}}')) as m:
            self.assertEqual(pr.autopilot("/a/hal2"), {"auto_prune": True})
        self.assertEqual(m.call_args.args[0], ["hal2-cli-agents", "autopilot", "show", "--json"])
        self.assertEqual(m.call_args.kwargs["cwd"], "/a/hal2")
        for answer in (done(1), done(0, "not json"), done(0, "[]")):
            with mock.patch.object(pr.bounded, "run", return_value=answer):
                self.assertIsNone(pr.autopilot("/a/hal2"))
        with mock.patch.object(pr.bounded, "run", side_effect=OSError("missing")):
            self.assertIsNone(pr.autopilot("/a/hal2"))

    def test_record_sets_pruned_to_the_rounds_start(self):
        with mock.patch.object(pr.bounded, "run", return_value=done(0)) as m:
            self.assertIsNone(pr.record("/a/hal2", "2026-11-03T12:00:00Z"))
        self.assertEqual(m.call_args.args[0][2:], ["set", "--pruned", "2026-11-03T12:00:00Z", "--json"])
        with mock.patch.object(pr.bounded, "run", return_value=done(2, "", "bad")):
            self.assertEqual(pr.record("/a/hal2", "x"), "record exit 2: bad")


if __name__ == "__main__":
    unittest.main()
