"""plan.py's commands of the one plan shape in a temp repository (hal2 plan 0376, row 7): `new` writes plan.md
schema 2 with its overview, `subplans/01-<slug>` and an empty `99-uat`; `subplan new` and `step add` number on and
regenerate the overview; `--schema 1`, `--parallel` and `--masterplan` keep the old step table; a step's status is
written into its file and the derived statuses follow."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import field_free
import envelope
import shape
import shape_new
from shape_names import ShapeError, StepRef

SCRIPT = Path(__file__).resolve().parent / "plan.py"


class ShapeCommandsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        self.env = {**os.environ, shape.CLI_ENV: str(self.root / "no-cli")}  # shape.py's own render

    def tearDown(self):
        self.tmp.cleanup()

    def run_plan(self, *args) -> subprocess.CompletedProcess:
        field_free.free(self.root, args)
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                              capture_output=True, text=True, cwd=self.root, env=self.env)

    def plan(self, *args) -> dict:
        result = self.run_plan(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def new(self, *args) -> Path:
        schema = () if "--schema" in args else ("--schema", "2")  # `new` defaults to schema 1 (hal2 plan 0376 D23)
        return (self.root / self.plan("new", *args, *schema)["path"]).parent

    def test_new_defaults_to_schema_1_until_the_readers_move(self):
        folder = (self.root / self.plan("new", "old default")["path"]).parent
        text = (folder / "plan.md").read_text()
        self.assertEqual(envelope.get(text, "schema"), 1)
        self.assertFalse((folder / "subplans").exists())

    def test_new_writes_the_one_plan_shape(self):
        folder = self.new("deploy the hub", "--goal", "The hub runs. Then more.")
        text = (folder / "plan.md").read_text()
        self.assertEqual((envelope.get(text, "schema"), envelope.get(text, "schedule")), (2, "serial"))
        for heading in ("## Goal", "## Brief", "## Context", "## Overview", "## Pre-authorized", "## Notes"):
            self.assertIn(heading + "\n", text)
        self.assertNotIn("## Steps", text)
        for name in ("decisions.md", "questions.md", "handoff.md", "subplans/01-deploy-the-hub/subplan.md",
                     "subplans/01-deploy-the-hub/steps/step-01.md", "subplans/01-deploy-the-hub/steps/step-02.md",
                     "subplans/99-uat/subplan.md"):
            self.assertTrue((folder / name).is_file(), name)
        found = shape.load(folder)
        self.assertEqual([str(s.id) for s in found.subplans], ["01-deploy-the-hub", "99-uat"])
        self.assertEqual(found.subplans[0].doc.description, "The hub runs.")
        self.assertEqual([s.derived() for s in found.subplans], ["open", "done"])
        self.assertEqual(found.uat().doc.shotfile, "deploy")
        self.assertEqual(shape.check_overview(folder), [])
        info = self.plan("current")
        self.assertEqual((info["total"], info["done"], info["next"]["number"]), (2, 0, "01.01"))
        self.assertEqual(info["steps"][-1]["step"].split("](")[0], "[Write the UATs and the changelog fragment")
        self.assertEqual(info["landing"], "auto")

    def test_a_research_plan_has_no_uat_writing_step_and_an_empty_99_uat(self):
        folder = self.new("compare tabs", "--research")
        found = shape.load(folder)
        self.assertEqual([len(s.steps) for s in found.subplans], [1, 0])
        self.assertEqual(self.plan("current")["landing"], "manual")

    def test_schema_1_parallel_and_masterplan_keep_the_step_table(self):
        for args in (["--schema", "1"], ["--parallel"], ["--masterplan"]):
            folder = self.new(f"old {args[0][2:]}", *args)
            self.assertFalse(shape.is_shape(folder), args)
            self.assertIn("## Steps", (folder / "plan.md").read_text())

    def test_subplan_new_numbers_on_and_opens_the_next_wave(self):
        folder = self.new("deploy the hub")
        info = self.plan("subplan", "new", "readers", "--goal", "Every reader works.")
        self.assertEqual((info["subplan"], info["wave"], info["overview"]), ("02-readers", 2, "shape.py"))
        self.assertEqual(self.plan("subplan", "new", "gui", "--wave", "2")["wave"], 2)
        found = shape.load(folder)
        self.assertEqual([str(s.id) for s in found.subplans], ["01-deploy-the-hub", "02-readers", "03-gui", "99-uat"])
        self.assertEqual(found.subplan(2).doc.description, "Every reader works.")
        self.assertIn("| [03 gui](subplans/03-gui/subplan.md) | 2 |", (folder / "plan.md").read_text())
        self.assertEqual(shape.check_overview(folder), [])
        self.assertEqual(self.run_plan("subplan", "new", "a plan with a rather long name").returncode, 1)

    def test_step_add_numbers_on_with_its_wave_and_sizing(self):
        folder = self.new("deploy the hub")
        info = self.plan("step", "add", "1", "Third", "--done-when", "it passes", "--size", "60k")
        self.assertEqual((info["ref"], info["wave"]), ("01.03", 3))
        self.plan("subplan", "new", "readers")
        info = self.plan("step", "add", "02-readers", "Statusline", "--wave", "4", "--model", "sonnet")
        self.assertEqual((info["ref"], info["wave"]), ("02.01", 4))
        step = shape.load(folder).step(StepRef(2, 1)).doc
        _, effort, window = shape_new.run_words(folder)  # the plan's `run`, the session's live values
        self.assertEqual((step.model, step.effort, step.window, step.size, step.status),
                         ("sonnet", effort, window, None, "open"))
        text = (folder / "plan.md").read_text()
        self.assertIn("| 01.03 | [Third](subplans/01-deploy-the-hub/steps/step-03.md) | it passes |", text)
        self.assertEqual(self.plan("current")["total"], 4)
        refused = self.run_plan("step", "add", "99", "a check")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("uat add", refused.stderr)

    def test_the_shape_commands_refuse_a_plan_of_schema_1(self):
        self.new("old plan", "--schema", "1")
        for args in (["subplan", "new", "x"], ["step", "add", "1", "x"], ["overview"]):
            result = self.run_plan(*args)
            self.assertEqual(result.returncode, 1, args)
            self.assertIn("schema 2", result.stderr)

    def test_a_step_status_is_written_into_its_file_and_the_statuses_follow(self):
        folder = self.new("deploy the hub")
        shape.write_step(folder, StepRef(1, 1), status="done", why="it ran")
        self.assertEqual(self.run_plan("overview", "--check").returncode, 1)  # written without the regeneration
        self.assertEqual(self.plan("overview", "--write")["overview"], "shape.py")
        self.assertEqual(self.run_plan("overview", "--check").returncode, 0)
        self.assertIn("\nstatus: running\n", (folder / "subplans/01-deploy-the-hub/subplan.md").read_text())
        shape.write_step(folder, StepRef(1, 2), status="dropped")
        shape.write_overview(self.root, folder)
        self.assertIn("\nstatus: done\n", (folder / "plan.md").read_text())
        self.assertIn("why: it ran\n", (folder / "subplans/01-deploy-the-hub/steps/step-01.md").read_text())
        with self.assertRaisesRegex(ShapeError, "StepStatus"):
            shape.write_step(folder, StepRef(1, 1), status="later")
        with self.assertRaisesRegex(ShapeError, "no step 01.09"):
            shape.write_step(folder, StepRef(1, 9), status="done")

    def test_overview_prints_the_block(self):
        folder = self.new("deploy the hub")
        out = self.run_plan("overview").stdout
        self.assertTrue(out.startswith("| Sub-plan | Wave |"))
        self.assertIn(out, (folder / "plan.md").read_text())


if __name__ == "__main__":
    unittest.main()
