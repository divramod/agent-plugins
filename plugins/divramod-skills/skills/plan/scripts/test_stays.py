"""A started plan stays its field's current plan (hal2 plan 0376 row 9; D2, D4, D5, D13, D15): `new` mid-plan adds a
sub-plan, `new --no-current` and `--here`, the refusals of `use` and `spec new`, `leave` on `uat` and its
PREVIOUS_PLAN restore, and a replay of field 02's incident (a big plan replaced by an unrelated one)."""
import subprocess
import sys
import unittest
from pathlib import Path

import occupied
from shape_testing import TempPlan

SPEC = Path(__file__).resolve().parents[2] / "spec" / "scripts" / "spec.py"


class StaysCurrentTest(TempPlan):
    def current(self) -> str:
        return (self.root / "plans" / "CURRENT_PLAN").read_text().strip()

    def previous(self) -> Path:
        return self.root / "plans" / "PREVIOUS_PLAN"

    def finish(self, folder: Path) -> None:
        """Every work step done (the plan is `uat`, or `done` without UAT steps)."""
        import shape
        for sub in shape.load(folder).work():
            for step in sub.steps:
                self.edit_step(folder, f"{sub.id.number:02d}.{step.number:02d}", status="done")

    def finish_schema1(self, slug: str) -> None:
        for step in self.plan("current")["steps"]:
            self.plan("status", step["number"], "done", "--plan", slug)

    def spec_new(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SPEC), "--repo", str(self.root), "new", *args],
                              capture_output=True, text=True, cwd=self.root)

    def test_a_fresh_plan_is_occupied_and_a_finished_one_is_not(self):
        folder = self.new("alpha plan")
        self.assertEqual(occupied.of(self.root), {"plan": folder.name, "status": "open", "schema": 2})
        self.finish(folder)
        self.assertIsNone(occupied.of(self.root))  # done: no UAT step open

    def test_new_mid_plan_adds_a_sub_plan_and_keeps_the_pointer(self):
        folder = self.new("alpha plan")
        out = self.plan("new", "beta work", "--goal", "Beta runs. More.")
        self.assertEqual(out, {"added": "subplan", "plan": folder.name, "subplan": "02-beta-work"})
        self.assertEqual(self.current(), folder.name)
        self.assertTrue((folder / "subplans" / "02-beta-work" / "subplan.md").is_file())
        self.assertEqual(sorted(p.name for p in (self.root / "plans").iterdir() if p.is_dir()), [folder.name])

    def test_new_mid_plan_on_schema_1_refuses_and_writes_nothing(self):
        old = self.new("old plan", "--schema", "1")
        before = (old / "plan.md").read_text()
        error = self.refused("new", "beta work")
        self.assertIn("--no-current", error)
        self.assertIn("--here", error)
        self.assertEqual((old / "plan.md").read_text(), before)
        self.assertEqual(self.current(), old.name)
        self.assertEqual(len(list((self.root / "plans").glob("0*"))), 1)

    def test_no_current_writes_a_separate_plan_and_the_pointer_stays(self):
        folder = self.new("alpha plan")
        other = self.new("servant work", "--no-current")
        self.assertNotEqual(other, folder)
        self.assertEqual(self.current(), folder.name)

    def test_here_keeps_the_old_plan_and_leave_restores_it(self):
        alpha = self.new("alpha plan")
        beta = self.new("beta plan", "--here")
        self.assertEqual((self.current(), self.previous().read_text().strip()), (beta.name, alpha.name))
        self.assertIn("already keeps", self.refused("new", "gamma plan", "--here"))
        self.assertEqual(self.plan("leave")["action"], "kept")  # beta is open
        self.finish(beta)
        out = self.plan("leave")
        self.assertEqual((out["action"], out["current"]), ("restored", alpha.name))
        self.assertEqual(self.current(), alpha.name)
        self.assertFalse(self.previous().exists())

    def test_leave_counts_uat_finished(self):
        folder = self.new("alpha plan")
        self.plan("uat", "add", "the page shows")
        self.finish(folder)
        self.assertEqual(self.plan("current")["status"], "uat")
        self.assertIsNone(occupied.of(self.root))
        self.assertEqual(self.plan("leave")["action"], "deleted")
        self.assertFalse((self.root / "plans" / "CURRENT_PLAN").exists())

    def test_leave_release_drops_previous_without_restoring(self):
        self.new("alpha plan")
        beta = self.new("beta plan", "--here")
        self.finish(beta)
        self.assertEqual(self.plan("leave", "--release")["action"], "deleted")
        self.assertFalse(self.previous().exists())

    def test_use_refuses_in_an_occupied_field_and_here_switches(self):
        alpha = self.new("alpha plan")
        beta = self.new("beta plan", "--no-current")
        error = self.refused("use", beta.name)
        self.assertIn("--here", error)
        self.assertIn("create.py --lead", error)
        self.assertEqual(self.current(), alpha.name)
        self.plan("use", alpha.name)  # the current plan itself is no switch
        self.plan("use", beta.name, "--here")
        self.assertEqual((self.current(), self.previous().read_text().strip()), (beta.name, alpha.name))

    @unittest.skipUnless(SPEC.is_file(), "needs the spec skill beside this one (not in the field-independence copy)")
    def test_spec_new_refuses_in_an_occupied_field(self):
        alpha = self.new("alpha plan")
        result = self.spec_new("A spec")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("--here", result.stderr)
        self.assertIn("create.py --lead", result.stderr)
        self.assertEqual(self.current(), alpha.name)
        self.assertEqual(len(list((self.root / "plans").glob("0*"))), 1)
        result = self.spec_new("A spec", "--here")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.previous().read_text().strip(), alpha.name)

    def test_field_02_replay(self):
        """A big plan (no masterplan marker) replaced by a plan without `parent:`; the landing's `leave` must give
        the field its big plan back, not delete the file."""
        big = self.new("whole roadmap", "--schema", "1")
        small = self.new("quick fix", "--schema", "1", "--here")
        self.assertEqual(self.current(), small.name)
        self.finish_schema1(small.name)
        out = self.plan("leave")
        self.assertEqual((out["action"], out["current"]), ("restored", big.name))
        self.assertEqual(self.current(), big.name)
        self.assertEqual(occupied.of(self.root)["plan"], big.name)
        self.assertEqual(self.plan("leave")["action"], "kept")  # the big plan has open steps
