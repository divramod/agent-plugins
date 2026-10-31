"""Hal2 plan 0349 step 10 (D6, D11): a red stack-test after the merge. The train stays landed; the board gets a `red`
line and each car's foreman the failing tests as a fix for its next harvest. Data only: no queue, no landing, no
session; the board line is written for real on the test farm."""

import contextlib
import datetime as dt
import io
import unittest
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import board
import stack_red
import trains
from engine_farm import OWN
from test_board import SCHEMA, Board, valid
from test_trains import TRAIN

LANDED = {"status": "landed", "commit": "c1", "run": "https://x/runs/9"}
RED = {"name": "03-hz-host-a/stack-test", "tests": ["daemon::socket_roundtrip", "hub::tenant_rls"]}


def shape(actions):
    return [(a["kind"], a["do"], a["slot"]) for a in actions]


class Rule(unittest.TestCase):
    def test_only_a_red_stack_test_job_counts(self):
        for result in (LANDED, {**LANDED, "red": []}, {**LANDED, "red": [{"name": "02-hz-a-lane/rust-test"}]},
                       {**LANDED, "red": [{"name": "03-hz-host-a/stack-test-extra"}]}, None):
            self.assertEqual(stack_red.red_jobs(result), [], result)
            self.assertEqual(stack_red.actions("/f", TRAIN, result, {}), [], result)
        self.assertEqual(stack_red.red_jobs({**LANDED, "red": [RED, {"name": "stack-test"}]}),
                         [RED, {"name": "stack-test"}], "a bare name counts too")
        # merge-to-main.yml's stack-test is a matrix job of a fixed name: GitHub appends its matrix value.
        suffixed = {"name": "03-hz01-host-a/stack-test (stack-test)"}
        self.assertEqual(stack_red.red_jobs({**LANDED, "red": [suffixed]}), [suffixed])

    def test_the_position_in_the_lane_is_no_part_of_the_job(self):
        # Plan 0349 D40: `<stage>-<alias>/<NN>-<job>`.
        positioned = {"name": "03-hz01-host-a/01-stack-test", "tests": ["hub::tenant_rls"]}
        self.assertEqual(stack_red.red_jobs({**LANDED, "red": [positioned]}), [positioned])
        suffixed = {"name": "03-hz01-host-a/01-stack-test (stack-test)"}
        self.assertEqual(stack_red.red_jobs({**LANDED, "red": [suffixed]}), [suffixed])
        for name in ("03-hz01-host-b/01-merge", "02-hz01-host-b/03-rust-lint", "03-hz01-host-a/01-stack-test-extra"):
            self.assertEqual(stack_red.red_jobs({**LANDED, "red": [{"name": name}]}), [], name)
        self.assertEqual(stack_red.stack_job([{"name": "03-hz01-host-b/01-merge"}, positioned]), positioned)
        self.assertEqual(shape(stack_red.actions("/f", TRAIN, {**LANDED, "red": [positioned]}, {}))[0],
                         ("stack-red", "run", "-"))

    def test_the_failing_tests_are_named_once_and_capped(self):
        self.assertEqual(stack_red.tests_of([RED, {"failed_tests": "hub::tenant_rls"}, {"tests": "a"}]),
                         ["daemon::socket_roundtrip", "hub::tenant_rls", "a"])
        many = {"tests": [f"t{i}" for i in range(14)]}
        text = stack_red.words([many])[0]
        self.assertTrue(text.startswith("t0, t1") and text.endswith("t9 and 4 more"), text)
        self.assertEqual(stack_red.words([{"name": "stack-test"}])[0], "the job's failing tests (read its log)")

    def test_a_landed_train_with_a_red_stack_test_logs_it_and_tells_no_car(self):
        """Plan 0490 step 3, D13: who fixes a red stack-test is the finished run's triage's, never the train's cars."""
        out = trains.settle("/f/tollman-hal2", TRAIN, {**LANDED, "red": [RED]}, {"07": "%7"})
        self.assertEqual(shape(out), [("landed", "run", "-"), ("in-the-barn", "send", "07"), ("in-the-barn", "send", "09"),
                                      ("stack-red", "run", "-"), ("chain", "run", "-")])
        log = out[3]
        self.assertEqual(log["after"], out[0]["key"], "the board line follows the landed verb")
        self.assertEqual(log["argv"][2:], ["post", "--kind", "red", "--from", "tollman-hal2", "--to", "-", "--train",
                                           TRAIN["train"], "--cars", "07,09", "--status", "stack-test", "--repo",
                                           "/f/tollman-hal2", "--text", log["argv"][-3], "--run", "https://x/runs/9"])
        self.assertIn("daemon::socket_roundtrip, hub::tenant_rls", log["argv"][-3])
        self.assertIn("the run's triage orders its owners", log["text"])
        self.assertEqual(len({a["key"] for a in out}), len(out), "every key is its own")

    def test_a_green_landing_and_a_red_train_get_no_stack_red_action(self):
        self.assertEqual(shape(trains.settle("/f", TRAIN, LANDED, {}))[-2:], [("in-the-barn", "send", "09"),
                                                                             ("chain", "run", "-")])
        red = trains.settle("/f", TRAIN, {"status": "gate_failed", "red": [RED]}, {})
        self.assertEqual(shape(red), [("red", "run", "-"), ("train-failed", "wake", "-")], "not landed: the old path")


class Watch(unittest.TestCase):
    """Merge no longer waits for stack-test (plan 0349 step 4): the land run's stack-test job is read itself, for the
    newest landed train, until it ends."""

    NOW = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.timezone.utc)
    ROW = {"kind": "landed", "at": "2026-10-15T10:00:00Z", "train": TRAIN["train"], "cars": ["07", "09"],
           "run": "https://github.com/divramod/hal2/actions/runs/38600000001"}

    def watch(self, jobs, rows=None, log=(), now=None):
        asked = []

        def fetch(rid):
            asked.append(rid)
            return jobs
        out = stack_red.watch("/f/tollman-hal2", "/f/main", [self.ROW] if rows is None else rows, {"07": "%7"},
                              list(log), fetch, now or self.NOW)
        return out, asked

    def test_a_red_stack_test_of_the_run_logs_it_and_marks_the_run_due_for_its_triage(self):
        out, asked = self.watch([{"name": "03-hz01-host-b/merge", "status": "completed", "conclusion": "success"},
                                 {"name": "03-hz01-host-a/stack-test (stack-test)", "status": "completed",
                                  "conclusion": "failure"}])
        self.assertEqual(asked, ["38600000001"])
        self.assertEqual(shape(out), [("stack-red", "run", "-"), ("run-triage", "run", "-")], "no car told (D13)")
        self.assertEqual(out[0]["key"], f"stack-red:{TRAIN['train']}")
        self.assertIn("03-hz01-host-a/stack-test (stack-test) is red: ", out[0]["argv"][-3])
        due = out[1]
        self.assertEqual((due["key"], due["after"]), ("run-triage:38600000001", out[0]["key"]))
        self.assertEqual(due["argv"][1:4], [str(Path(stack_red.__file__).with_name("run_triage_wire.py")), "due",
                                            "--repo"])
        self.assertIn("https://github.com/divramod/hal2/actions/runs/38600000001", due["argv"])

    def test_a_run_whose_triage_started_is_never_read(self):
        self.assertEqual(self.watch([], log=[{"key": "run-triage:38600000001"}]), ([], []))

    def test_a_red_positioned_stack_test_of_the_run_counts(self):
        out, _ = self.watch([{"name": "03-hz01-host-b/01-merge", "status": "completed", "conclusion": "success"},
                             {"name": "03-hz01-host-a/01-stack-test", "status": "completed", "conclusion": "failure"}])
        self.assertEqual(shape(out)[0], ("stack-red", "run", "-"))
        self.assertIn("03-hz01-host-a/01-stack-test is red", out[0]["text"])

    def test_a_red_stack_test_of_the_matrix_alias_names_counts(self):
        # Plan 0349 D101: `<matrix alias>-<NN>-<job>`, the merge as `d2-01-git-merge`.
        new = {"name": "d1-01-stack-test", "tests": ["hub::tenant_rls"]}
        self.assertEqual(stack_red.red_jobs({**LANDED, "red": [new]}), [new])
        for name in ("d2-01-git-merge", "c3-03-rust-lint", "d1-01-stack-test-extra", "d1-01-stack"):
            self.assertEqual(stack_red.red_jobs({**LANDED, "red": [{"name": name}]}), [], name)
        out, _ = self.watch([{"name": "d2-01-git-merge", "status": "completed", "conclusion": "success"},
                             {"name": "d1-01-stack-test", "status": "completed", "conclusion": "failure"}])
        self.assertEqual(shape(out)[0], ("stack-red", "run", "-"))
        self.assertIn("d1-01-stack-test is red", out[0]["text"])

    def test_a_running_stack_test_waits_and_a_green_one_ends_the_watch(self):
        running = [{"name": "03-hz01-host-a/stack-test", "status": "in_progress", "conclusion": ""}]
        self.assertEqual(self.watch(running)[0], [])
        green = [{"name": "03-hz01-host-a/stack-test", "status": "completed", "conclusion": "success"}]
        out, _ = self.watch(green)
        self.assertEqual([(a["kind"], a["do"], a["key"]) for a in out],
                         [("stack-done", "record", f"stack-done:{TRAIN['train']}")])
        skipped = [{"name": "03-hz01-host-a/stack-test", "status": "completed", "conclusion": "skipped"}]
        self.assertEqual(shape(self.watch(skipped)[0]), [("stack-done", "record", "-")])

    def test_no_read_once_settled_too_old_without_a_run_or_a_landed_train(self):
        for key in (f"stack-red:{TRAIN['train']}", f"stack-done:{TRAIN['train']}"):
            self.assertEqual(self.watch([], log=[{"key": key}]), ([], []), key)
        self.assertEqual(self.watch([], now=self.NOW + dt.timedelta(hours=5)), ([], []), "past WATCH_HOURS")
        self.assertEqual(self.watch([], rows=[{**self.ROW, "run": None}]), ([], []))
        self.assertEqual(self.watch([], rows=[{"kind": "formed", "train": "x"}]), ([], []))
        self.assertEqual(stack_red.run_id("38600000001"), "38600000001")


class OnTheBoard(Board):
    def test_the_action_posts_a_valid_red_line_for_the_train_s_cars(self):
        out = trains.settle(str(self.wm), TRAIN, {**LANDED, "red": [RED]}, {})
        argv = next(a["argv"] for a in out if a["kind"] == "stack-red")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(board.main(argv[2:]), 0)
        line = board.lines(self.main_dir(), "red")[-1]
        self.assertEqual((valid(SCHEMA, line), line["status"], line["cars"], line["train"], line["run"]),
                         ([], "stack-test", ["07", "09"], TRAIN["train"], "https://x/runs/9"))
        self.assertEqual((line["from"], line["slot"]), (OWN, OWN))
        self.assertIn("03-hz-host-a/stack-test is red: daemon::socket_roundtrip, hub::tenant_rls", line["text"])


if __name__ == "__main__":
    unittest.main()
