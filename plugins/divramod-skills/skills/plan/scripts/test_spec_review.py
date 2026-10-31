"""Plan 0502 step 6 (D6): a spec changed after its plan had steps flags the plan (`spec_review` in plan.md, set by
spec.py update); `plan.py check` reports it as rule `plan-spec-review`, `current` carries it, `spec.py reviewed`
clears it; and `plan.py leave` clears CURRENT_PLAN after a spec in state spec was brought in for later. Scratch
repositories, the real spec skill beside the plan skill."""
import json
import tempfile
import unittest
from pathlib import Path

import field_free
import spec_link
import testkit

HERE = Path(__file__).resolve().parent
PLAN = HERE / "plan.py"
SPEC = HERE.parent.parent / "spec" / "scripts" / "spec.py"
LABEL = "plans/0007-login-speed/plan.md"


def plan_text(extra: str = "") -> str:
    return f"---\ntype: Plan\nschema: 1\nid: 7\ntitle: x\nstatus: open\n{extra}---\n\n# Plan 0007: x\n"


class ReviewRuleTest(unittest.TestCase):
    """The rule on plan.md text alone: no process, no repository."""

    def test_a_plan_without_the_flag_has_no_problem(self):
        self.assertEqual(spec_link.review(plan_text()), 0)
        self.assertEqual(spec_link.review_problems(plan_text(), LABEL), [])

    def test_a_flagged_plan_is_reported_with_its_round_and_the_command_that_clears_it(self):
        text = plan_text("spec_review: 3\n")

        self.assertEqual(spec_link.review(text), 3)
        self.assertEqual(spec_link.review_problems(text, LABEL), [
            f"{LABEL}: the spec changed in round 3: review the Brief and the steps, then `spec.py reviewed 7` "
            "(plan-spec-review)"])

    def test_a_legacy_plan_without_front_matter_has_no_problem(self):
        self.assertEqual(spec_link.review_problems("# Plan 0007: x\n\n- Spec: y\n", LABEL), [])


@unittest.skipUnless(SPEC.is_file(), "needs the spec skill beside this one (not in the field-independence copy)")
class SpecLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        testkit.init_repo(self.root)
        self.plans = self.root / "plans"

    def tearDown(self):
        self.tmp.cleanup()

    def cmd(self, script, *args, ok=True):
        field_free.free(self.root, args)
        result = testkit.run(script, ["--root", str(self.root), *args], cwd=self.root) if script == PLAN \
            else testkit.run_spec(self.root, *args)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def planned_spec(self) -> Path:
        info = json.loads(self.cmd(SPEC, "new", "login speed", "--json").stdout)
        self.cmd(PLAN, "new", "--spec", "1")
        return self.root / info["folder"]

    def test_a_spec_update_flags_the_planned_plan_check_reports_it_and_reviewed_clears_it(self):
        folder = self.planned_spec()
        self.assertEqual(json.loads(self.cmd(PLAN, "current").stdout)["spec_review"], 0)
        self.assertNotIn("plan-spec-review", self.cmd(PLAN, "check", ok=False).stdout)

        self.cmd(SPEC, "update", "1", "--what", "single sign-on is in")

        self.assertEqual(json.loads(self.cmd(PLAN, "current").stdout)["spec_review"], 1)
        checked = self.cmd(PLAN, "check", ok=False)
        self.assertEqual(checked.returncode, 1)
        self.assertIn(f"plans/{folder.name}/plan.md: the spec changed in round 1: review the Brief and the steps, "
                      "then `spec.py reviewed 1` (plan-spec-review)", checked.stdout)
        as_json = json.loads(self.cmd(PLAN, "check", "--json", ok=False).stdout)
        self.assertTrue(any("plan-spec-review" in p for p in as_json["problems"]))

        self.cmd(SPEC, "reviewed", "1")

        self.assertEqual(json.loads(self.cmd(PLAN, "current").stdout)["spec_review"], 0)
        self.assertNotIn("plan-spec-review", self.cmd(PLAN, "check", ok=False).stdout)

    def test_a_spec_update_before_planning_sets_no_flag_and_planning_clears_a_stray_one(self):
        info = json.loads(self.cmd(SPEC, "new", "second idea", "--json").stdout)
        folder = self.root / info["folder"]
        self.cmd(SPEC, "update", "1", "--what", "reworded")
        self.assertNotIn("spec_review", (folder / "plan.md").read_text())

        text = (folder / "plan.md").read_text().replace("status: spec\n", "status: spec\nspec_review: 4\n")
        (folder / "plan.md").write_text(text)
        self.cmd(PLAN, "new", "--spec", "1")

        self.assertNotIn("spec_review", (folder / "plan.md").read_text())

    def test_leave_clears_current_plan_after_a_spec_was_brought_in_for_later(self):
        folder = self.root / json.loads(self.cmd(SPEC, "new", "login speed", "--json").stdout)["folder"]
        self.assertEqual((self.plans / "CURRENT_PLAN").read_text(), folder.name + "\n")

        left = json.loads(self.cmd(PLAN, "leave").stdout)

        self.assertEqual(left["action"], "deleted")
        self.assertIn("spec brought in for later", left["line"])
        self.assertFalse((self.plans / "CURRENT_PLAN").exists())

    def test_leave_still_keeps_a_planned_spec_with_open_steps(self):
        folder = self.planned_spec()

        left = json.loads(self.cmd(PLAN, "leave").stdout)

        self.assertEqual(left["action"], "kept")
        self.assertEqual((self.plans / "CURRENT_PLAN").read_text(), folder.name + "\n")

    def test_leave_after_an_abandoned_spec_is_not_the_spec_rule(self):
        folder = self.root / json.loads(self.cmd(SPEC, "new", "login speed", "--json").stdout)["folder"]
        self.cmd(SPEC, "abandon", "1")
        self.assertIn("status: abandoned", (folder / "plan.md").read_text())

        left = json.loads(self.cmd(PLAN, "leave").stdout)

        self.assertNotIn("spec brought in for later", left["line"])


if __name__ == "__main__":
    unittest.main()
