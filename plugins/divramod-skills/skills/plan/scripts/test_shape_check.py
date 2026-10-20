"""`plan.py check` on the one plan shape (hal2 plan 0376, row 8): one seeded fault per rule (plan-shape,
plan-steps-sized, spec:budgets lines and cells, overview-current, status-derived, waves-disjoint) under the rule ids
hal2-records reports, a clean new plan passing, the old checker's findings on schema 2 dropped when it is older than
0.7.0, and the golden fixture read in place."""
import json
import stat
import unittest

import shape_check
from shape_testing import TempPlan, fixture

ROOT = fixture()


class CheckTest(TempPlan):
    def setUp(self):
        super().setUp()
        self.env["HAL2_CLI_RECORDS"] = str(self.root / "no-records")  # the skill's own rules only
        self.folder = self.new("deploy the hub")
        self.plan_md = self.folder / "plan.md"

    def rules(self) -> list[str]:
        out = self.run_plan("check", "--json")
        return [line.rsplit("(", 1)[-1].rstrip(")") for line in json.loads(out.stdout)["problems"]
                if "plan-brief-filled" not in line]

    def test_a_new_plan_has_no_shape_problem(self):
        self.assertEqual(self.rules(), [])

    def test_plan_steps_sized(self):
        self.edit_step(self.folder, "01.01", size="500k")
        self.run_plan("overview", "--write")
        self.assertEqual(self.rules(), ["plan-steps-sized"])
        self.edit_step(self.folder, "01.01", status="done")
        self.assertEqual(self.rules(), ["overview-current", "status-derived"])

    def test_budget_lines_outside_the_block_and_cells(self):
        self.plan_md.write_text(self.plan_md.read_text() + "\n" + "line\n" * 160)
        self.assertEqual(self.rules(), ["spec:budgets"])
        self.plan_md.write_text(self.plan_md.read_text().replace("line\n" * 160, "| a |\n|---|\n| " + "x" * 250 + " |\n"))
        self.assertEqual(self.rules(), ["spec:budgets"])

    def test_overview_current(self):
        self.plan_md.write_text(self.plan_md.read_text().replace("| open |", "| done |", 1))
        self.assertEqual(self.rules(), ["overview-current"])

    def test_status_derived(self):
        self.edit_subplan(self.folder, 1, status="done")
        self.assertEqual(self.rules(), ["status-derived"])
        self.run_plan("overview", "--write")
        self.set_plan_key(self.folder, "finished", "2026-10-18")
        self.assertEqual(self.rules(), ["status-derived"])

    def test_waves_disjoint(self):
        self.set_plan_key(self.folder, "schedule", "waves")
        self.plan("subplan", "new", "cli", "--wave", "1")
        self.edit_subplan(self.folder, 1, touches=["docs", "@vm"])
        self.edit_subplan(self.folder, 2, touches=["docs", "@vm"])
        self.run_plan("overview", "--write")
        self.assertEqual(self.rules(), ["waves-disjoint"])
        self.edit_subplan(self.folder, 2, touches=["@vm"])
        self.assertEqual(self.rules(), [])

    def test_plan_shape(self):
        stray = self.folder / "subplans/05-gone/steps/step-01.md"
        stray.parent.mkdir(parents=True)
        stray.write_text((self.folder / "subplans/01-deploy-the-hub/steps/step-01.md").read_text())
        self.assertEqual(self.rules(), ["plan-shape"])

    def test_an_old_records_checker_is_skipped_on_schema_2(self):
        fake = self.root / "old-records"
        fake.write_text('#!/bin/sh\n[ "$1" = "--version" ] && { echo "hal2-cli-records 0.5.0"; exit 0; }\n'
                        'echo \'{"records": 1, "problems": [{"path": "plans/0001-deploy-the-hub/plan.md", '
                        '"message": "schema 2", "rule": "spec:schema"}]}\'\nexit 1\n')
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.env["HAL2_CLI_RECORDS"] = str(fake)
        out = self.run_plan("check", "--json")
        self.assertIn("0.5.0 is older than 0.7.0", out.stdout)
        self.assertNotIn("spec:schema", out.stdout)


@unittest.skipUnless(ROOT, "the golden fixture is in the hal2 repository only")
class GoldenCheckTest(unittest.TestCase):
    def test_the_fixture_has_only_its_unsized_open_step(self):
        problems = shape_check.problems(ROOT.parent, ROOT)
        self.assertEqual({p.rsplit("(", 1)[-1] for p in problems}, {"plan-steps-sized)"})
        self.assertTrue(all("step 02.03" in p for p in problems), problems)
        self.assertEqual(len(problems), 4)


if __name__ == "__main__":
    unittest.main()
