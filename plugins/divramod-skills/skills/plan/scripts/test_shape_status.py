"""plan.py's step commands on the one plan shape (hal2 plan 0376, row 8): `status <ref>`, `current`, `trailers`,
`assign` and `uat add` in a temp repository, and `current` on hal2-core's golden fixture, read in place."""
import unittest

import envelope
import plan
import shape
import shape_status
from shape_testing import TempPlan, fixture

ROOT = fixture()


class StatusTest(TempPlan):
    def test_status_takes_a_ref_writes_the_step_file_and_regenerates(self):
        folder = self.new("deploy the hub")
        self.assertIn("e.g. `01.01`", self.refused("status", "1", "done"))
        info = self.plan("status", "01.01", "done", "--why", "it ran")
        self.assertEqual((info["written"]["ref"], info["written"]["overview"]), ("01.01", "shape.py"))
        self.assertEqual((info["done"], info["total"], info["ref"], info["subplan"]), (1, 2, "01.02", "01-deploy-the-hub"))
        self.assertIn("why: it ran\n", (folder / "subplans/01-deploy-the-hub/steps/step-01.md").read_text())
        self.assertEqual(shape.check_overview(folder), [])
        self.assertIn("no step 01.07", self.refused("status", "01.07", "done"))
        self.assertIn("verdict", self.refused("status", "99.01", "done"))

    def test_finished_is_set_while_the_plan_is_uat_or_done(self):
        folder = self.new("deploy the hub")
        self.plan("uat", "add", "The hub answers", "--steps", "open it", "--expected", "it answers")
        self.plan("status", "01.01", "done")
        info = self.plan("status", "01.02", "dropped")
        self.assertEqual((info["status"], info["done"], info["ref"], info["uat_open"]), ("uat", 2, None, 1))
        self.assertTrue(envelope.get((folder / "plan.md").read_text(), "finished"))
        self.plan("status", "01.02", "open")
        text = (folder / "plan.md").read_text()
        self.assertEqual((envelope.get(text, "status"), envelope.get(text, "finished")), ("open", None))

    def test_ledgers_close_with_uat_and_open_with_the_plan(self):
        folder = self.new("deploy the hub")
        ledger = folder / "decisions.md"
        ledger.write_text("---\ntype: Decisions\nschema: 1\nplan: 1\ntitle: t\ndescription: d\nstatus: open\n---\n")
        self.plan("uat", "add", "The hub answers", "--steps", "open it", "--expected", "it answers")
        self.plan("status", "01.01", "done")
        self.assertEqual(envelope.get(ledger.read_text(), "status"), "open")
        self.plan("status", "01.02", "done")
        self.assertEqual(envelope.get(ledger.read_text(), "status"), "closed")
        self.plan("status", "01.02", "open")
        self.assertEqual(envelope.get(ledger.read_text(), "status"), "open")

    def test_uat_add_refuses_a_description_over_200_characters(self):
        self.new("deploy the hub")
        self.assertIn("at most 200", self.refused("uat", "add", "Long", "--expected", "x" * 201))

    def test_current_has_the_old_keys_plus_ref_and_subplan(self):
        folder = self.new("deploy the hub")
        self.plan("subplan", "new", "readers")
        self.plan("step", "add", "2", "Statusline", "--size", "40k")
        info = self.plan("current")
        for key in ("slug", "path", "done", "total", "next", "landing", "land", "problems", "steps", "ref", "subplan"):
            self.assertIn(key, info)
        self.assertEqual((info["total"], info["ref"], info["next"]["number"], info["land"]), (3, "01.01", "01.01", "wait"))
        self.edit_step(folder, "02.01", status="running")
        self.assertEqual(self.plan("current")["ref"], "02.01")

    def test_trailers_count_the_work_steps(self):
        self.new("deploy the hub")
        self.assertEqual(self.run_plan("trailers", "01.02").stdout,
                         "Worktree: 07\nPlan: 0001-deploy-the-hub\nStep: 2/2\n")
        self.plan("status", "01.01", "running")
        self.assertIn("Step: 1/2\n", self.run_plan("trailers").stdout)
        self.assertIn("no ref", self.refused("trailers", "2"))

    def test_assign_sets_who_and_regenerates(self):
        folder = self.new("deploy the hub")
        self.assertEqual(self.plan("assign", "1", "field", "31")["who"], "field 31")
        self.assertEqual(shape.load(folder).subplan(1).doc.who, "field 31")
        self.assertIsNone(self.plan("assign", "01", "-")["who"])
        self.assertIn("none of", self.refused("assign", "1", "lead"))
        self.assertIn("uat add", self.refused("assign", "99", "foreman"))

    def test_uat_add_writes_a_uat_step_in_99_uat(self):
        folder = self.new("deploy the hub")
        info = self.plan("uat", "add", "The hub answers", "--open", "hal9k://hub", "--steps", "open it", "click Ping",
                         "--expected", "Ping says pong", "--priority", "p1", "--tags", "smoke")
        self.assertEqual((info["ref"], info["check"], info["overview"]), ("99.01", "U1", "shape.py"))
        doc = shape.load(folder).uat().steps[0].doc
        self.assertEqual((doc.status, doc.priority, doc.tags, doc.description), ("open", "p1", ["smoke"],
                                                                                  "Ping says pong"))
        self.assertIn("Open: hal9k://hub\nSteps:\n1. open it\n2. click Ping\n\nExpected: Ping says pong\n", doc.body)
        self.assertEqual(self.plan("uat", "add", "Second")["check"], "U2")
        self.assertIn("| [99 uat](subplans/99-uat/subplan.md) | - |", (folder / "plan.md").read_text())
        self.assertEqual(shape.check_overview(folder), [])
        self.assertIn("uat add", self.refused("uat"))

    def test_schema_1_keeps_its_commands(self):
        folder = self.new("old plan", "--schema", "1")
        self.plan("status", "1", "done")
        self.assertIn("Step: 1/", self.run_plan("trailers", "1").stdout)
        self.plan("uat", "add", "ignored")
        self.assertTrue((folder / "uat.md").is_file())


class ServantFieldTest(TempPlan):
    def lead(self, token: str) -> None:
        (self.root / "plans/LEAD").write_text(f"07 0001-deploy-the-hub {token}\n")

    def test_a_subplan_servant_writes_only_its_steps(self):
        folder = self.new("deploy the hub")
        self.plan("subplan", "new", "readers")
        self.plan("step", "add", "2", "Statusline", "--size", "40k")
        before = (folder / "plan.md").read_text()
        self.lead("02-readers")
        info = self.plan("status", "02.01", "done")
        self.assertIn("skipped", info["written"]["overview"])
        self.assertEqual((folder / "plan.md").read_text(), before)
        self.assertIn("status: done", (folder / "subplans/02-readers/steps/step-01.md").read_text())
        self.assertIn("sub-plan 02-readers only", self.refused("status", "01.01", "done"))
        for args in (["subplan", "new", "x"], ["step", "add", "2", "x"], ["assign", "2", "foreman"],
                     ["uat", "add", "x"], ["subplan", "start", "2"], ["overview", "--write"]):
            self.assertIn("servant of sub-plan 02-readers", self.refused(*args), args)
        self.assertEqual(self.run_plan("overview", "--check").returncode, 1)  # stale, the foreman's to write
        self.assertNotIn("overview-current", self.run_plan("check").stdout)
        self.assertNotIn("status-derived", self.run_plan("check").stdout)

    def test_a_legacy_lead_keeps_the_old_refusal(self):
        self.new("deploy the hub")
        self.lead("3")
        self.assertIn("is the foreman's", self.refused("status", "01.01", "done"))


@unittest.skipUnless(ROOT, "the golden fixture is in the hal2 repository only")
class GoldenCurrentTest(unittest.TestCase):
    def test_current_on_the_fixture(self):
        base = plan.describe(ROOT.parent, ROOT / "plan.md")
        info = shape_status.current(ROOT, base)
        self.assertEqual((info["status"], info["done"], info["total"]), ("open", 3, 5))
        self.assertEqual((info["ref"], info["subplan"], info["next"]["number"]), ("02.02", "02-readers", "02.02"))
        self.assertEqual((info["uat_checks"], info["uat_open"]), (["U1", "U2", "U3"], 2))

    def test_trailers_on_the_fixture(self):
        self.assertEqual(shape_status.trailer_lines(ROOT.parent, ROOT, None)[1:],
                         ["Plan: plan-shape", "Step: 4/5"])


if __name__ == "__main__":
    unittest.main()
