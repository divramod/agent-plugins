"""runstate.py and `plan.py state` (hal2 plan 0514 step 1, D2-D4): the gitignored per-field run state beside
CURRENT_PLAN, in either home; `status next` writes working, the last step done writes done, `leave` clears the file.
Scratch repositories only; none needs hal2."""
import contextlib
import io
import json
import unittest
from unittest import mock

import pointers
import runstate
import test_plan
import test_masterplan as base

SLUG = "0002-migrate-daily-tools"


class RunStateModuleTest(unittest.TestCase):
    setUp, tearDown = base.MasterplanTest.setUp, base.MasterplanTest.tearDown

    def current(self, slug: str = SLUG) -> None:
        pointers.write(self.root, pointers.CURRENT_PLAN, slug)

    def test_write_then_read_round_trips_with_schema_and_utc_time(self):
        self.current()
        runstate.write(self.root, SLUG, "blocked", "needs a key")
        found = runstate.read(self.root)
        self.assertEqual((found["schema"], found["plan"], found["state"], found["why"]),
                         (1, SLUG, "blocked", "needs a key"))
        self.assertRegex(found["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(json.loads((self.plans / "PLAN_STATE").read_text())["state"], "blocked")

    def test_waiting_and_blocked_need_a_why_and_the_state_must_be_known(self):
        self.current()
        for state in ("waiting", "blocked"):
            with self.assertRaises(runstate.StateError):
                runstate.write(self.root, SLUG, state)
            with self.assertRaises(runstate.StateError):
                runstate.write(self.root, SLUG, state, "  ")
        with self.assertRaises(runstate.StateError):
            runstate.write(self.root, SLUG, "napping")
        with self.assertRaises(runstate.StateError):
            runstate.write(self.root, "", "working")
        self.assertIsNone(runstate.read(self.root))
        for state in ("working", "pushing", "done", "hitched", "landed"):
            self.assertEqual(runstate.write(self.root, SLUG, state)["state"], state)

    def test_a_file_naming_another_plan_reads_as_none(self):
        self.current()
        runstate.write(self.root, SLUG, "working")
        self.current("0003-other")
        self.assertIsNone(runstate.read(self.root))
        self.assertEqual(runstate.read(self.root, SLUG)["state"], "working")
        self.assertTrue(runstate.clear_stale(self.root))
        self.assertFalse((self.plans / "PLAN_STATE").exists())

    def test_a_bad_file_reads_as_none(self):
        self.current()
        file = self.plans / "PLAN_STATE"
        file.parent.mkdir(exist_ok=True)
        good = {"schema": 1, "plan": SLUG, "state": "working", "why": "", "at": "2026-10-30T10:00:00Z"}
        for text in ("", "not json", "[1]", json.dumps({**good, "schema": 2}), json.dumps({**good, "state": "x"}),
                     json.dumps({**good, "plan": ""})):
            file.write_text(text)
            self.assertIsNone(runstate.read(self.root), text)
        file.write_text(json.dumps(good))
        self.assertEqual(runstate.read(self.root)["state"], "working")

    def test_the_write_is_atomic_and_leaves_no_temp_file(self):
        self.current()
        runstate.write(self.root, SLUG, "working")
        with mock.patch.object(runstate.os, "replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                runstate.write(self.root, SLUG, "done")
        self.assertEqual(runstate.read(self.root)["state"], "working")  # the old file untouched
        self.assertEqual(sorted(p.name for p in self.plans.iterdir()), ["CURRENT_PLAN", "PLAN_STATE"])

    def test_the_store_home_writes_the_git_dir_and_removes_the_old_copy(self):
        self.current()
        runstate.write(self.root, SLUG, "working")
        self.assertTrue((self.plans / "PLAN_STATE").is_file())
        with mock.patch.object(pointers, "in_store", return_value=True):
            runstate.write(self.root, SLUG, "pushing")
        self.assertFalse((self.plans / "PLAN_STATE").exists())
        git_file = self.root / ".git" / "hal" / "PLAN_STATE"
        self.assertEqual(json.loads(git_file.read_text())["state"], "pushing")
        self.assertEqual(runstate.read(self.root)["state"], "pushing")
        with mock.patch.object(pointers, "in_store", return_value=False):  # back to the files home
            runstate.write(self.root, SLUG, "done")
        self.assertFalse(git_file.exists())
        self.assertEqual(runstate.read(self.root)["state"], "done")
        runstate.clear(self.root)
        self.assertIsNone(runstate.read(self.root))

    def test_a_state_only_in_the_git_dir_is_read(self):
        self.current()
        git_file = self.root / ".git" / "hal" / "PLAN_STATE"
        git_file.parent.mkdir(parents=True, exist_ok=True)
        git_file.write_text(json.dumps({"schema": 1, "plan": SLUG, "state": "hitched", "why": "", "at": "x"}))
        self.assertEqual(runstate.read(self.root)["state"], "hitched")

    def test_after_status_rules(self):
        self.current()
        self.assertIsNone(runstate.after_status(self.root, "0003-other", "next", False))  # not this field's plan
        self.assertEqual(runstate.after_status(self.root, SLUG, "next", False)["state"], "working")
        self.assertIsNone(runstate.after_status(self.root, SLUG, "done", False))
        self.assertEqual(runstate.read(self.root)["state"], "working")
        self.assertEqual(runstate.after_status(self.root, SLUG, "done (`abc`)", True)["state"], "done")
        self.assertEqual(runstate.after_status(self.root, SLUG, "next", False)["state"], "working")
        runstate.write(self.root, SLUG, "blocked", "x")
        self.assertIsNone(runstate.after_status(self.root, SLUG, "blocked why", False))  # other states stay
        self.assertEqual(runstate.read(self.root)["state"], "blocked")

    def test_the_pointers_shell_knows_the_name(self):
        self.current()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pointers.main(["write", str(self.root), "PLAN_STATE", "x"]), 0)
        self.assertTrue((self.plans / "PLAN_STATE").is_file())


class RunStateCommandTest(unittest.TestCase):
    """`plan.py state` and the hooks of `status` and `leave`, through the script."""
    setUp, tearDown = test_plan.PlanTest.setUp, test_plan.PlanTest.tearDown
    run_plan, plan, write_plan = test_plan.PlanTest.run_plan, test_plan.PlanTest.plan, test_plan.PlanTest.write_plan

    def state_file(self):
        return self.plans / "PLAN_STATE"

    def test_state_without_a_current_plan_is_refused(self):
        result = self.run_plan("state", "working")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no plan", result.stderr)
        self.assertEqual(self.run_plan("state").stdout.strip(), "none")

    def test_state_sets_prints_and_requires_why(self):
        self.write_plan()
        self.plan("use", "2")
        self.assertEqual(self.run_plan("state", "waiting").returncode, 1)
        self.assertIn("--why", self.run_plan("state", "waiting").stderr)
        self.assertEqual(self.run_plan("state", "waiting", "--why", "CI").stdout.strip(), "waiting (CI)")
        shown = json.loads(self.run_plan("state", "--json").stdout)
        self.assertEqual((shown["plan"], shown["state"], shown["why"], shown["schema"]), (SLUG, "waiting", "CI", 1))
        self.assertEqual(self.run_plan("state").stdout.strip(), "waiting (CI)")
        self.assertEqual(self.run_plan("state", "napping").returncode, 2)  # argparse choices

    def test_state_json_without_a_file_names_the_plan_and_no_state(self):
        self.write_plan()
        self.plan("use", "2")
        shown = json.loads(self.run_plan("state", "--json").stdout)
        self.assertEqual((shown["plan"], shown["state"]), (SLUG, None))

    def test_status_next_writes_working_and_the_last_done_writes_done(self):
        self.write_plan()
        self.plan("use", "2")
        self.plan("status", "2", "done")
        self.assertFalse(self.state_file().exists())  # step 3 is open: not finished
        self.plan("status", "3", "next")
        self.assertEqual(json.loads(self.state_file().read_text())["state"], "working")
        self.plan("status", "3", "done")
        self.assertEqual(json.loads(self.state_file().read_text())["state"], "done")
        self.plan("status", "3", "next")  # reopened
        self.assertEqual(json.loads(self.state_file().read_text())["state"], "working")

    def test_a_plan_of_schema_2_follows_its_steps_too(self):
        self.plan("new", "Two", "--schema", "2")
        self.plan("status", "01.01", "next")
        self.assertEqual(json.loads(self.state_file().read_text())["state"], "working")
        self.plan("status", "01.01", "done")
        self.assertEqual(json.loads(self.state_file().read_text())["state"], "working")
        self.plan("status", "01.02", "done")
        self.assertEqual(json.loads(self.state_file().read_text())["state"], "done")

    def test_status_on_another_plan_leaves_the_state_alone(self):
        self.write_plan()
        self.write_plan("0003-other", test_plan.EXISTING)
        self.plan("use", "2")
        self.plan("status", "3", "next")
        before = self.state_file().read_text()
        self.plan("status", "3", "done", "--plan", "3")
        self.plan("status", "2", "next", "--plan", "3")
        self.assertEqual(self.state_file().read_text(), before)

    def test_the_state_is_gitignored_like_current_plan(self):
        ignore = base.hal2_file(".gitignore")
        if ignore is None:
            self.skipTest("an installed plugin: no hal2 checkout around it")
        text = ignore.read_text().splitlines()
        self.assertIn("plans/CURRENT_PLAN", text)
        self.assertIn("plans/PLAN_STATE", text)

    def test_leave_clears_the_state_of_a_finished_plan_but_keeps_an_open_ones(self):
        self.write_plan()
        self.plan("use", "2")
        self.plan("status", "3", "next")
        self.plan("leave")  # step 3 still open: the pointer stays, so does the state
        self.assertTrue(self.state_file().exists())
        self.plan("status", "2", "done")
        self.plan("status", "3", "done")
        self.assertEqual(json.loads(self.state_file().read_text())["state"], "done")
        self.plan("leave")
        self.assertFalse((self.plans / "CURRENT_PLAN").exists())
        self.assertFalse(self.state_file().exists())


if __name__ == "__main__":
    unittest.main()
