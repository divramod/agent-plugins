"""Hal2 plan 0360 step 5 (D4, D32): while a train's landing runs, each tick reads its land run; the first red job
wakes the session once, keyed by the run. The run is found by its branch (hal2-git's `current` for the carrier, else the `started` line's) and its time, and cached
as a `run` line of train.jsonl. gh is gh_fake.py's: no real call."""

import datetime as dt
import json
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import land_name
import tick
import train_state
import trains
import watch
from gh_fake import FakeGh, job, run

AT = "2026-10-17T10:00:00Z"
NAME = "07+09@" + AT
TOP, MAIN = "/no/such/farm/tollman-hal2", "/no/such/farm"
CARS = [{"field": "07", "branch": "07", "head": "7" * 40, "plan": "0360-tollman-and-skills"},
        {"field": "09", "branch": "09", "head": "9" * 40, "plan": ""}]


def line(kind, at=AT, **kw):
    return {"schema": 1, "at": at, "kind": kind, "slot": "tollman-hal2", "train": NAME, **kw}


FORMED = line("formed", cars=CARS, base="b" * 40)
STARTED = line("started", at="2026-10-17T10:05:00Z", pid=4711, land_ref="train-7-1")
OURS = run(501, "land/train-7-1", "2026-10-17T10:06:00Z", status="in_progress")


def shape(actions):
    return [(a["kind"], a["do"], a["key"]) for a in actions]


class LocalPhase(unittest.TestCase):
    """Plan 0467 D21, D23: the train's first `run` line carries `local_phase_seconds` (formed → the run's creation)."""

    def phase(self, rows, runs, url=OURS["url"]):
        FakeGh(runs).start(self)
        train = train_state.standing(rows)
        return watch.local_phase_seconds(MAIN, train, rows, url, dt.datetime(2026, 10, 17, 12, 0, tzinfo=dt.timezone.utc))

    def test_the_first_run_line_measures_formed_to_the_runs_creation(self):
        self.assertEqual(self.phase([FORMED, STARTED], [OURS]), 360.0)  # formed 10:00, run created 10:06

    def test_a_run_gh_does_not_list_is_measured_to_the_moment_of_the_note(self):
        self.assertEqual(self.phase([FORMED, STARTED], []), 7200.0)

    def test_a_later_run_line_of_the_same_train_has_none(self):
        rows = [FORMED, STARTED, line("run", at="2026-10-17T10:07:00Z", run=OURS["url"]), STARTED]
        self.assertIsNone(self.phase(rows, [OURS]))


def no_cli(args, cwd):  # hal2-cli-git cannot say: the started line's branch stands (no real call in a test)
    return 127, "no hal2-cli-git"


class Watch(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(land_name, "cli", no_cli)
        patch.start()
        self.addCleanup(patch.stop)

    def watch(self, gh, rows=(FORMED, STARTED)):
        gh.start(self)
        rows = list(rows)
        return trains.plan(TOP, MAIN, [], rows, {}, alive=lambda pid: pid == 4711, result=lambda main: None)

    def test_a_live_landing_whose_run_has_no_red_job_does_nothing_but_note_its_run(self):
        gh = FakeGh([OURS], jobs={"501": [job("d1-01-rust-test", None), job("a1-01-bash-lint", "success")]})
        out = self.watch(gh)
        self.assertEqual(shape(out), [("train-run", "run", f"train-run:{NAME}:501")])
        self.assertEqual(out[0]["argv"][2:], ["run", OURS["url"], "--repo", TOP])
        cached = [FORMED, STARTED, line("run", at="2026-10-17T10:07:00Z", run=OURS["url"])]
        self.assertEqual(self.watch(FakeGh(jobs=gh.jobs), cached), [], "cached: no list, no action")

    def test_the_first_red_job_wakes_once_keyed_by_the_run(self):
        gh = FakeGh([OURS], jobs={"501": [job("d1-01-rust-test", "failure"), job("d1-02-ts-test", None)]},
                    logs={"501": "test hub::tenant_rls ... FAILED\nassertion failed"})
        first = self.watch(gh)
        self.assertEqual(shape(first), [("train-run", "run", f"train-run:{NAME}:501"),
                                        ("early-red", "record", "early-red:501:d1-01-rust-test"),  # 0522 D17
                                        ("train-red", "wake", "train-red:501")])
        wake = first[2]
        for part in (f"train {NAME} is red while it lands", "d1-01-rust-test", OURS["url"],
                     "Cars: 07 (0360-tollman-and-skills), 09 (09).", "tollman.py triage 501"):
            self.assertIn(part, wake["text"])
        self.assertEqual(wake["evidence"]["kind"], "car")
        log = [{"at": "2026-10-17T10:10:00", "key": a["key"]} for a in first]
        again = self.watch(FakeGh([OURS], jobs=gh.jobs, logs=gh.logs))
        now = dt.datetime(2026, 10, 17, 10, 11)
        self.assertEqual(tick.fresh(again, log, now, "tollman"), [], "the same tick twice: one wake")

    def test_the_run_is_found_by_branch_and_time_and_a_retry_s_newer_run_wins(self):
        runs = [run(509, "land/0360-tollman-and-skills-1", "2026-10-17T11:30:00Z", status="in_progress"),  # a field's
                run(508, "land/train-7-2", "2026-10-17T11:20:00Z", status="in_progress"),  # the retry's run
                run(507, "land/train-7-1", "2026-10-17T10:06:00Z"),  # the first start's, red
                run(400, "land/train-6-1", "2026-10-16T09:00:00Z")]  # an earlier train's
        retried = [FORMED, STARTED, line("run", at="2026-10-17T10:07:00Z", run=runs[2]["url"]),
                   line("red", at="2026-10-17T11:00:00Z", status="gate_failed", run=runs[2]["url"]),
                   line("retry", at="2026-10-17T11:01:00Z", why="runner: ECONNRESET"),
                   line("started", at="2026-10-17T11:15:00Z", pid=4711, land_ref="train-7-2")]
        self.assertIsNone(train_state.land_run(retried), "the run of an earlier start is not this start's")
        out = self.watch(FakeGh(runs), retried)
        self.assertEqual(shape(out), [("train-run", "run", f"train-run:{NAME}:508")])
        FakeGh([runs[0], runs[2], runs[3]]).start(self)  # before the retry: its own run, never another slot's
        self.assertEqual(watch.find(MAIN, train_state.standing([FORMED, STARTED]), [FORMED, STARTED]),
                         (runs[2]["url"], True), "the first start's: after it, on its own branch")
        self.assertEqual(watch.find(MAIN, train_state.standing([FORMED]), [FORMED]), (None, False),
                         "never started: no run")

    def test_hal2_git_s_current_branch_beats_the_started_line_and_a_line_without_one_finds_no_run(self):
        fake = lambda args, cwd: (0, json.dumps({"schema": 1, "slot": "tollman-hal2", "kind": "train",
                                                 "current": "land/train-7-2", "next": "land/train-7-3"}))
        seen = []
        FakeGh([run(701, "land/train-7-2", "2026-10-17T10:20:00Z", status="in_progress"), OURS]).start(self)
        rows = [FORMED, STARTED]
        with mock.patch.object(land_name, "cli", lambda args, cwd: seen.append((args, cwd)) or fake(args, cwd)):
            self.assertEqual(watch.find(MAIN, train_state.standing(rows), rows)[0], "https://github.com/x/actions/runs/701")
        self.assertEqual(seen, [(["worktree", "land-ref", "--slot", "tollman-hal2", "--json"], MAIN)])
        bare = [FORMED, line("started", at="2026-10-17T10:05:00Z", pid=4711)]
        self.assertEqual(watch.find(MAIN, train_state.standing(bare), bare), (None, False), "never a built name")


class Record(unittest.TestCase):
    def test_the_run_line_is_cached_in_the_train_state_and_standing_keeps_its_state(self):
        rows = [FORMED, STARTED, line("run", at="2026-10-17T10:07:00Z", run=OURS["url"])]
        t = train_state.standing(rows)
        self.assertEqual((t["state"], t["starts"], train_state.land_run(rows)), ("landing", 1, OURS["url"]))
        self.assertIn("run", train_state.KINDS)


if __name__ == "__main__":
    unittest.main()
