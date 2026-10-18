"""masterplan_keep.py through plan.py (hal2 plan 0275 step 5): a masterplan's row ticked by code and the tick taken
back, with and without `--plan`; `plan.py leave` after a bring in; `after_landing` of `plan.py masterplan --json`.

Every test works in a scratch repository; none needs hal2 (test_masterplan.py's fixture, whose helpers it borrows)."""
import unittest

import test_masterplan as base
import testkit

MASTER = base.MASTER
TOOLS, VIEW = "0002-tools", "0003-view"
UAT_CHECK = "`plan.py current` shows `uat` with its checks"


class KeepTest(unittest.TestCase):
    setUp, tearDown = base.MasterplanTest.setUp, base.MasterplanTest.tearDown
    run_plan, plan, refused = base.MasterplanTest.run_plan, base.MasterplanTest.plan, base.MasterplanTest.refused
    write, farm = base.MasterplanTest.write, base.MasterplanTest.farm

    def two_plans(self):
        """A masterplan with the plans 0002-tools (row 1) and 0003-view (row 2, the current plan); its plan.md. Made
        once by `new`, later tests start from a copy (testkit.fill_once)."""
        def build():
            self.farm()
            self.plan("new", "view", "--parent", "1")
        if self.plans.exists():
            build()
        else:
            testkit.fill_once("two_plans", self.root, build)
        return self.plans / MASTER / "plan.md"

    def row(self, master, number: str) -> str:
        """The Status cell of the masterplan's row `number`."""
        line = next(l for l in master.read_text().splitlines() if l.startswith(f"| {number} | ["))
        return line.rstrip(" |").rsplit("|", 1)[1].strip()

    def pointer(self) -> str | None:
        file = self.plans / "CURRENT_PLAN"
        return file.read_text() if file.exists() else None

    def finish(self, plan: str) -> dict:
        self.plan("status", "1", "done", "--plan", plan)
        return self.plan("status", "2", "done", "--plan", plan)

    # the tick

    def test_a_plan_that_turns_done_ticks_its_row_and_a_reopened_step_takes_the_tick_back(self):
        master = self.farm()  # 0002-tools is the current plan and the masterplan's only row
        self.assertNotIn("tick", self.plan("status", "1", "done"))
        self.assertEqual(self.row(master, "1"), "draft")

        info = self.plan("status", "2", "done")
        self.assertEqual(info["tick"], {"masterplan": MASTER, "row": "1", "status": "done",
                                        "masterplan_finished": True})
        self.assertEqual((self.row(master, "1"), info["finished"] != ""), ("done", True))
        self.assertIn("status: done\n", master.read_text())  # the masterplan's own stamp follows
        self.assertIn("finished: ", master.read_text())
        self.assertNotIn("tick", self.plan("status", "2", "done (0c1f)"))  # nothing changed: no second tick

        info = self.plan("status", "2", "next")
        self.assertEqual(info["tick"], {"masterplan": MASTER, "row": "1", "status": "running",
                                        "masterplan_finished": False})
        self.assertEqual(self.row(master, "1"), "running")
        self.assertIn("status: open\n", master.read_text())
        self.assertNotIn("finished: ", master.read_text())

    def test_the_foreman_ticks_a_servants_plan_with_plan_from_its_own_field(self):
        master = self.two_plans()
        self.plan("use", "1")  # the field names the masterplan; the servant's plan is marked with --plan

        info = self.finish(TOOLS)
        self.assertEqual(info["tick"], {"masterplan": MASTER, "row": "1", "status": "done",
                                        "masterplan_finished": False})
        self.assertEqual((self.row(master, "1"), self.row(master, "2")), ("done", "draft"))
        self.assertIn("status: open\n", master.read_text())
        self.assertEqual(self.pointer(), MASTER + "\n")
        self.assertEqual(self.plan("status", "1", "next", "--plan", TOOLS)["tick"]["status"], "running")
        self.assertEqual(self.row(master, "1"), "running")

    def test_a_row_keeps_its_note_and_a_plan_without_a_row_ticks_nothing(self):
        master = self.farm()
        self.finish(TOOLS)
        master.write_text(master.read_text().replace("| done |", "| done (brought in with 0003) |"))
        self.assertNotIn("tick", self.plan("status", "2", "done (again)", "--plan", TOOLS))
        self.assertEqual(self.row(master, "1"), "done (brought in with 0003)")
        before = master.read_text()
        self.write("0005-lonely", keys="parent: 1\n")  # names the masterplan, which has no row for it
        self.write("0006-child", keys="parent: 5\n")  # its parent is an ordinary plan
        for plan in ("5", "6"):
            info = self.plan("status", "1", "done", "--plan", plan)
            self.assertTrue(info["finished"])
            self.assertNotIn("tick", info)
        self.assertEqual(master.read_text(), before)

    # plan.py leave

    def test_leave_names_the_unfinished_masterplan_after_a_plan_of_it(self):
        master = self.two_plans()
        self.plan("use", TOOLS)
        kept = self.plan("leave")
        self.assertEqual((kept["action"], kept["current"], self.pointer()), ("kept", TOOLS, TOOLS + "\n"))
        self.assertIn("step(s) 1, 2 open", kept["line"])

        self.finish(TOOLS)
        left = self.plan("leave")
        self.assertEqual((left["was"], left["current"], left["action"]), (TOOLS, MASTER, "masterplan"))
        self.assertIn(f"names the masterplan {MASTER} now: {TOOLS}, its row 1, is finished", left["line"])
        self.assertEqual(self.pointer(), MASTER + "\n")
        self.assertTrue(self.plan("current")["masterplan"])

        between = self.plan("leave")  # the masterplan itself, between two plans: left alone
        self.assertEqual((between["action"], self.pointer()), ("kept", MASTER + "\n"))
        self.assertIn("row(s) 2 open", between["line"])
        self.assertEqual(self.row(master, "1"), "done")

    def test_leave_deletes_the_file_after_the_masterplans_last_plan_and_after_a_plan_of_none(self):
        master = self.farm()
        self.finish(TOOLS)
        left = self.plan("leave")
        self.assertEqual((left["was"], left["current"], left["action"]), (TOOLS, "", "deleted"))
        self.assertIsNone(self.pointer())
        self.assertIn("status: done\n", master.read_text())
        self.assertEqual(self.plan("leave")["action"], "none")

        self.write("0007-alone")
        self.plan("use", "7")
        self.plan("status", "1", "done")
        self.assertEqual(self.plan("leave")["action"], "deleted")
        self.plan("use", "1")  # the finished masterplan itself
        self.assertEqual((self.plan("leave")["action"], self.pointer()), ("deleted", None))

    def test_leave_deletes_a_shot_or_task_and_keeps_a_plan_it_cannot_read(self):
        for name in ("shooter/3/some-shot", "fix-the-login"):
            self.plans.mkdir(exist_ok=True)
            (self.plans / "CURRENT_PLAN").write_text(name + "\n")
            left = self.plan("leave")
            self.assertEqual((left["was"], left["action"], self.pointer()), (name, "deleted", None))
        (self.plans / "CURRENT_PLAN").write_text("0042-elsewhere\n")
        left = self.plan("leave")
        self.assertEqual((left["action"], self.pointer()), ("kept", "0042-elsewhere\n"))
        self.assertIn("holds no such plan", left["line"])

    def test_leave_is_refused_in_a_servants_field(self):
        self.two_plans()
        self.plan("use", "1")
        (self.plans / "LEAD").write_text(f"09 {MASTER} 1\n")
        error = self.refused("leave")
        self.assertIn(f"a servant of the foreman in field 09 (plan {MASTER} row 1)", error)
        self.assertIn("`leave` is the foreman's", error)
        self.assertEqual(self.pointer(), MASTER + "\n")
        self.assertIn("works on a repository only", self.refused("leave", pre=("--global-root", str(self.base / "g"))))

    def test_leave_deletes_a_file_that_holds_only_whitespace(self):
        self.plans.mkdir()
        (self.plans / "CURRENT_PLAN").write_text(" \n\n")  # mtm's after-landing.sh takes any byte for a name (`-s`)
        left = self.plan("leave")
        self.assertEqual((left["was"], left["action"], self.pointer()), ("", "none", None))
        self.assertIn("the empty file is deleted", left["line"])

    def test_leave_takes_a_done_plan_without_steps_as_finished_and_keeps_an_open_one(self):
        for slug, status, action, pointer in (("0008-stepless", "done", "deleted", None),
                                              ("0009-unwritten", "open", "kept", "0009-unwritten\n")):
            path = self.write(slug, status)
            path.write_text(path.read_text().split("| # |")[0])  # no step table
            (self.plans / "CURRENT_PLAN").write_text(slug + "\n")
            left = self.plan("leave")
            self.assertEqual((left["action"], self.pointer()), (action, pointer), left["line"])
        self.assertIn("it has no step", left["line"])

    def test_leave_release_frees_a_field_that_does_not_carry_on_with_the_masterplan(self):
        self.two_plans()
        self.plan("use", TOOLS)
        kept = self.plan("leave", "--release")  # open steps: a release frees no unfinished work
        self.assertEqual((kept["action"], self.pointer()), ("kept", TOOLS + "\n"))

        self.finish(TOOLS)
        left = self.plan("leave", "--release")
        self.assertEqual((left["was"], left["current"], left["action"], self.pointer()), (TOOLS, "", "deleted", None))
        self.assertIn(f"{TOOLS}, its row 1, is finished and the field is released from the masterplan {MASTER}",
                      left["line"])
        (self.plans / "CURRENT_PLAN").write_text(MASTER + "\n")  # a plain `leave` ran first: it names the masterplan
        left = self.plan("leave", "--release")
        self.assertEqual((left["action"], self.pointer()), ("deleted", None))
        self.assertIn(f"released from the masterplan {MASTER}", left["line"])

        (self.plans / "CURRENT_PLAN").write_text(MASTER + "\n")
        (self.plans / "LEAD").write_text(f"09 {MASTER} 1\n")
        self.assertIn("`leave` is the foreman's", self.refused("leave", "--release"))
        self.assertEqual(self.pointer(), MASTER + "\n")

    def test_leave_names_no_row_where_the_masterplan_has_none_for_the_plan(self):
        self.farm()
        self.write("0005-lonely", keys="parent: 1\n")  # names the masterplan, which has no row for it
        self.plan("status", "1", "done", "--plan", "5")
        (self.plans / "CURRENT_PLAN").write_text("0005-lonely\n")
        left = self.plan("leave")
        self.assertEqual((left["action"], left["current"]), ("masterplan", MASTER))
        self.assertIn(f"names the masterplan {MASTER} now: 0005-lonely is finished", left["line"])
        self.assertNotIn("None", left["line"])

    # after_landing

    def test_masterplan_names_the_plans_whose_open_steps_are_all_checked_after_the_landing(self):
        self.two_plans()
        tools = self.plans / TOOLS / "plan.md"
        tools.write_text(tools.read_text().replace(UAT_CHECK, "after the landing: the installed binary answers"))
        self.assertEqual(self.plan("masterplan", "--json")["after_landing"], [])  # step 1 is open before the landing
        self.plan("status", "1", "done", "--plan", TOOLS)

        info = self.plan("masterplan", "--json")  # the current plan is 0003-view: the other plan is named
        self.assertEqual(info["after_landing"], [{"row": "1", "plan": TOOLS, "steps": ["2"]}])
        lines = self.run_plan("masterplan").stdout.splitlines()
        self.assertIn(f"after the landing: row 1 {TOOLS} step(s) 2", lines)
        self.assertEqual(self.plan("status", "2", "done", "--plan", TOOLS)["tick"]["row"], "1")
        self.assertEqual(self.plan("masterplan", "--json")["after_landing"], [])


if __name__ == "__main__":
    unittest.main()
