"""plan.py: create, list, switch and update plans (plans/<NNNN>-<slug>/plan.md)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "plan.py"

EXISTING = """# Plan 0002: migrate daily tools

| # | Step | Status |
|---|---|---|
| 1 | git status | done (`c649bd5`) |
| 2 | move nvim | next |
| 3 | shooter | |
"""


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        self.plans = self.root / "plans"

    def tearDown(self):
        self.tmp.cleanup()

    def write_plan(self, slug="0002-migrate-daily-tools", text=EXISTING) -> Path:
        path = self.plans / slug / "plan.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_plan(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                              capture_output=True, text=True)

    def plan(self, *args) -> dict:
        result = self.run_plan(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_new_research_plan_slug_starts_with_research(self):
        info = self.plan("new", "macOS plugin runtimes", "--research")

        self.assertEqual(info["slug"], "0001-research-macos-plugin-runtimes")
        self.assertTrue(info["research"])
        self.assertEqual((self.plans / "CURRENT_PLAN").read_text(), "0001-research-macos-plugin-runtimes\n")

    def test_new_research_plan_keeps_a_leading_research(self):
        info = self.plan("new", "Research: plugin runtimes", "--research")

        self.assertEqual(info["slug"], "0001-research-plugin-runtimes")

    def test_plain_plan_is_no_research_plan(self):
        info = self.plan("new", "researcher view")

        self.assertEqual(info["slug"], "0001-researcher-view")
        self.assertFalse(info["research"])

    def test_new_numbers_after_existing_and_becomes_current(self):
        self.write_plan()
        (self.plans / "0001-old").mkdir()  # a folder without plan.md is no plan

        info = self.plan("new", "Lean Shooter CLI!", "--goal", "Replace the old binary.")

        self.assertEqual(info["slug"], "0003-lean-shooter-cli")
        self.assertTrue(info["current"])
        self.assertEqual((self.plans / "CURRENT_PLAN").read_text(), "0003-lean-shooter-cli\n")
        text = (self.plans / "0003-lean-shooter-cli" / "plan.md").read_text()
        self.assertIn("# Plan 0003: Lean Shooter CLI!", text)
        self.assertIn("Replace the old binary.", text)
        self.assertEqual(info["total"], 2)  # the step and the UAT step
        self.assertEqual(info["path"], "plans/0003-lean-shooter-cli/plan.md")
        self.assertEqual([p["slug"] for p in self.plan("list")], ["0002-migrate-daily-tools", "0003-lean-shooter-cli"])

    def test_current_reports_progress_and_next_step(self):
        self.write_plan()
        (self.plans / "CURRENT_PLAN").write_text("0002-migrate-daily-tools\n")

        info = self.plan("current")

        self.assertEqual((info["done"], info["total"]), (1, 3))
        self.assertEqual(info["next"]["number"], "2")
        self.assertEqual(info["next"]["done_when"], "")
        self.assertEqual(info["grilled"], "")

    def test_a_legacy_step_takes_the_run_default_a_record_step_names_its_own(self):
        self.write_plan(text="# Plan 0002: x\n\nRun: sonnet medium\n\n## Steps\n\n"
                             "| # | Step | Done when | Model | Effort | Status |\n|---|---|---|---|---|---|\n"
                             "| 1 | a | t | opus | high | next |\n| 2 | b | t | | xhigh | |\n")
        (self.plans / "CURRENT_PLAN").write_text("0002-migrate-daily-tools\n")

        info = self.plan("current")

        self.assertEqual([(s["model"], s["effort"]) for s in info["steps"]], [("opus", "high"), ("sonnet", "xhigh")])
        self.assertEqual((info["next"]["model"], info["next"]["effort"]), ("opus", "high"))
        self.write_plan()
        self.assertEqual(self.plan("current")["next"]["model"], "", "a legacy table runs on the session's own")
        # A record plan's `run` is the coordinator's: a row's empty cell stays empty (the check names it).
        self.write_plan(text="---\ntype: Plan\nrun: opus max 1m\n---\n\n# Plan 0002: x\n\n"
                             "| # | Step | Done when | Model | Effort | Window | Size | Status |\n"
                             "|---|---|---|---|---|---|---|---|\n| 1 | a | t | | high | 1m | 90k | next |\n")
        step = self.plan("current")["next"]
        self.assertEqual((step["model"], step["effort"], step["window"], step["size"]), ("", "high", "1m", "90k"))

    def test_status_updates_one_cell(self):
        self.write_plan()
        (self.plans / "CURRENT_PLAN").write_text("0002-migrate-daily-tools\n")

        self.plan("status", "2", "done (`916a934`)")
        info = self.plan("status", "3", "next")

        self.assertEqual(info["done"], 2)
        self.assertEqual(info["next"]["step"], "shooter")
        self.assertIn("| 2 | move nvim | done (`916a934`) |", (self.plans / "0002-migrate-daily-tools" / "plan.md").read_text())

    def test_status_next_writes_the_step_file_once(self):
        self.write_plan(text=EXISTING.replace("| 3 | shooter | |", "| 3 | shooter `x` | |"))
        (self.plans / "CURRENT_PLAN").write_text("0002-migrate-daily-tools\n")
        step = self.plans / "0002-migrate-daily-tools" / "steps" / "3.md"

        info = self.plan("status", "3", "next")

        self.assertEqual(info["step_file"], "plans/0002-migrate-daily-tools/steps/3.md")
        text = step.read_text()
        self.assertTrue(text.startswith("# Step 3: shooter `x`\n"))
        self.assertIn("\n## Task\n", text)
        self.assertIn("plans-short-and-concise", text)
        self.assertNotIn("Size:", text)  # a legacy row names no Size or Window
        step.write_text("# Step 3: mine\n\n## Task\n\nkept\n")
        info = self.plan("status", "3", "next")
        self.assertNotIn("step_file", info)
        self.assertIn("kept", step.read_text())
        self.plan("status", "2", "done")
        self.assertFalse((step.parent / "2.md").exists())

    def test_use_accepts_number_and_grilled_stamps_date(self):
        self.write_plan()

        self.plan("use", "2")
        info = self.plan("grilled")

        self.assertTrue(info["current"])
        self.assertRegex(info["grilled"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(self.plan("grilled")["grilled"], info["grilled"])  # idempotent, one line

    def test_last_step_done_stamps_finished_and_reopening_removes_it(self):
        info = self.plan("new", "Tiny")
        path = self.root / info["path"]
        self.assertEqual(info["finished"], "")
        self.plan("status", "1", "done")
        self.assertNotIn("finished:", path.read_text())
        self.plan("status", "2", "done")
        text = path.read_text()
        self.assertRegex(text, r"\nstatus: done\n(.*\n)*finished: \d{4}-\d{2}-\d{2}\n---\n")
        self.assertTrue(self.plan("current")["finished"])
        self.plan("status", "2", "next")
        self.assertNotIn("finished:", path.read_text())
        self.assertIn("\nstatus: open\n", path.read_text())

    def test_a_legacy_plan_keeps_its_finished_line(self):
        path = self.write_plan(text=EXISTING.replace("next |", "done |"))
        self.plan("use", "2")
        self.plan("status", "3", "done")
        self.assertRegex(path.read_text(), r"\nFinished: \d{4}-\d{2}-\d{2}\n")
        self.plan("status", "3", "next")
        self.assertNotIn("Finished:", path.read_text())

    def test_new_plan_ends_with_the_uat_step_but_a_research_plan_does_not(self):
        info = self.plan("new", "plugin-plan 3 tabs")
        self.assertEqual([s["step"].split(":")[0] for s in info["steps"]][-1], "Write the UATs")
        research = self.plan("new", "Compare tabs", "--research")
        self.assertFalse(any("UAT" in s["step"] for s in research["steps"]))

    def test_new_plan_has_a_pre_authorized_section_and_its_decisions_in_the_ledger(self):
        """Hal2 plan 0137: user-only questions are answered before implementation and recorded; hal2 plan 0206: a
        plan's decisions are the entries of decisions.md, no section of plan.md."""
        info = self.plan("new", "deploy the hub")
        text = (self.root / info["path"]).read_text()
        self.assertIn("## Pre-authorized", text)
        self.assertNotIn("## Decisions", text)
        self.assertEqual(info["decisions"], "plans/0001-deploy-the-hub/decisions.md")
        self.assertEqual(len(info["steps"]), 2)

    def test_uat_scaffolds_once_with_the_feature_shotfile(self):
        info = self.plan("new", "plugin-plan 3 tabs")
        self.assertEqual((info["uat"], info["uat_checks"]), ("", []))
        info = self.plan("uat")
        uat = self.root / info["uat"]
        text = uat.read_text()
        self.assertTrue(text.startswith("---\ntype: UAT\nschema: 1\ntitle: \"plugin-plan 3 tabs\"\n"), text)
        self.assertIn("\nstatus: active\n", text)
        self.assertIn(f"\nplan: {int(info['slug'][:4])}\n", text)
        self.assertIn(f"\n# UAT {info['slug'][:4]}: plugin-plan 3 tabs\n", text)
        self.assertIn("\nshotfile: plugin-plan\n", text)
        self.assertNotIn("Shotfile:", text, "the typed form: the envelope holds the header")
        self.assertEqual(info["uat_checks"], ["U1"])
        uat.write_text(text + "\n## U2 Second\nSteps:\n1. x\n\nExpected: y\n")
        self.assertEqual(self.plan("uat", "--shotfile", "other")["uat_checks"], ["U1", "U2"])  # never overwritten

    def test_grilled_auto_counts_autogrill_rounds(self):
        self.write_plan()
        self.plan("use", "2")
        self.assertEqual(self.plan("current")["autogrill_rounds"], 0)

        info = self.plan("grilled", "--auto")
        self.assertRegex(info["grilled"], r"^\d{4}-\d{2}-\d{2} \(autogrill ×1\)$")
        self.assertEqual(info["autogrill_rounds"], 1)
        info = self.plan("grilled", "--auto")
        self.assertRegex(info["grilled"], r"\(autogrill ×2\)$")
        info = self.plan("grilled")
        self.assertRegex(info["grilled"], r"\(autogrill ×2, grill\)$")
        self.assertEqual(self.plan("grilled", "--auto")["autogrill_rounds"], 3)

    def test_flat_plan_from_before_the_folder_layout_still_works(self):
        self.plans.mkdir(parents=True)
        (self.plans / "0002-migrate-daily-tools.md").write_text(EXISTING)

        info = self.plan("use", "0002-migrate-daily-tools")

        self.assertEqual((info["slug"], info["path"]), ("0002-migrate-daily-tools", "plans/0002-migrate-daily-tools.md"))
        self.assertEqual(self.plan("status", "2", "done")["done"], 2)

    def test_errors(self):
        self.assertEqual(self.run_plan("current").returncode, 1)
        self.write_plan()
        self.assertEqual(self.run_plan("use", "9").returncode, 1)
        self.assertEqual(self.run_plan("status", "7", "x", "--plan", "2").returncode, 1)
        self.assertEqual(self.run_plan("new", "!!!").returncode, 1)

    def test_new_plan_lands_automatically_unless_manual(self):
        info = self.plan("new", "Auto")
        self.assertEqual(info["landing"], "auto")
        self.assertIn("\nlanding: auto\n", (self.root / info["path"]).read_text())
        self.assertEqual(info["land"], "wait")

        info = self.plan("new", "Manual", "--manual-landing")
        self.assertEqual(info["landing"], "manual")
        self.assertEqual(info["land"], "manual")

    def test_new_research_plan_never_lands_itself(self):
        info = self.plan("new", "Compare queues", "--research")
        self.assertEqual(info["landing"], "manual")
        self.assertIn("\nlanding: manual\n", (self.root / info["path"]).read_text())
        self.assertEqual(info["land"], "manual")

    def test_new_autogenerated_plan_names_its_maker(self):
        self.assertEqual(self.plan("new", "Plain")["autogenerated"], "")
        info = self.plan("new", "Watcher fix", "--autogenerated", "sanity-watch")
        self.assertTrue(info["autogenerated"].startswith("sanity-watch, 20"), info["autogenerated"])
        text = (self.root / info["path"]).read_text()
        self.assertIn("\nautogenerated: sanity-watch, ", text)
        self.assertIn("\nlanding: auto\n", text)

    def test_plan_without_landing_line_is_manual_and_landing_sets_it(self):
        self.write_plan()
        self.assertEqual(self.plan("use", "2")["landing"], "manual")

        info = self.plan("landing", "auto")
        self.assertEqual(info["landing"], "auto")
        self.assertEqual(info["land"], "wait")
        text = (self.plans / "0002-migrate-daily-tools" / "plan.md").read_text()
        self.assertTrue(text.startswith("# Plan 0002: migrate daily tools\n\nLanding: auto\n"))

        self.assertEqual(self.plan("landing", "manual")["landing"], "manual")
        text = (self.plans / "0002-migrate-daily-tools" / "plan.md").read_text()
        self.assertEqual(text.count("Landing:"), 1)
        self.assertEqual(self.run_plan("landing", "later").returncode, 2)

    def test_land_is_ready_when_only_after_landing_steps_are_open(self):
        self.write_plan(text="""# Plan 0002: x

Landing: auto

| # | Step | Done when | Status |
|---|---|---|---|
| 1 | build | `cargo test` | done |
| 2 | install | after the landing: `x --version` works | |
| 3 | old style | after the user's `/mtm`: `y` works | |
""")
        info = self.plan("use", "2")
        self.assertEqual(info["land"], "ready")
        self.assertEqual([s["after_landing"] for s in info["steps"]], [False, True, True])
        self.assertEqual(info["next"]["number"], "2")
        self.assertEqual(info["problems"], [])

        self.plan("status", "1", "next")
        self.assertEqual(self.plan("current")["land"], "wait")

    def test_after_landing_step_before_others_is_a_problem_and_not_next(self):
        self.write_plan(text="""# Plan 0002: x

Landing: auto

| # | Step | Done when | Status |
|---|---|---|---|
| 1 | install | after the landing: `x` works | |
| 2 | build | `cargo test` | |
""")
        info = self.plan("use", "2")
        self.assertEqual(info["next"]["number"], "2")
        self.assertEqual(info["land"], "wait")
        self.assertEqual(len(info["problems"]), 1)
        self.assertIn("step 1", info["problems"][0])

    def test_current_names_a_shot_not_a_plan(self):
        self.write_plan()
        (self.plans / "CURRENT_PLAN").write_text("shooter/1\n")
        result = self.run_plan("current")
        self.assertEqual(result.returncode, 1)
        self.assertIn("names 'shooter/1', which is not a plan", result.stderr)


class GlobalPlanTest(unittest.TestCase):
    """plan.py -g: the global plans folder, no git, no CURRENT_PLAN."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "global-plans"
        (self.folder / "0001-life").mkdir(parents=True)
        (self.folder / "0001-life" / "plan.md").write_text(EXISTING.replace("0002", "0001"))
        # A fake hal2-cli-plans that creates what `new --global` would.
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        fake = self.bin / "hal2-cli-plans"
        fake.write_text(f"""#!/bin/sh
mkdir -p {self.folder}/0002-next
printf '# Plan 0002: Next\\n\\n| # | Step | Status |\\n|---|---|---|\\n| 1 | a | next |\\n' > {self.folder}/0002-next/plan.md
echo '{{"slug": "0002-next", "path": "{self.folder}/0002-next/plan.md"}}'
""")
        fake.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_plan(self, *args) -> subprocess.CompletedProcess:
        env = {"PATH": f"{self.bin}:/usr/bin:/bin"}
        return subprocess.run([sys.executable, str(SCRIPT), "-g", "--global-root", str(self.folder), *args],
                              capture_output=True, text=True, env=env)

    def plan(self, *args):
        result = self.run_plan(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_list_status_and_grilled_on_a_named_plan(self):
        self.assertEqual([p["slug"] for p in self.plan("list")], ["0001-life"])
        info = self.plan("status", "2", "done", "--plan", "1")
        self.assertEqual(info["done"], 2)
        self.assertFalse(info["current"])
        self.assertTrue(self.plan("grilled", "--plan", "1")["grilled"])

    def test_new_goes_through_hal2(self):
        info = self.plan("new", "Next")
        self.assertEqual(info["slug"], "0002-next")
        self.assertEqual(info["next"]["number"], "1")

    def test_global_plans_never_land(self):
        info = self.plan("list")[0]
        self.assertEqual((info["landing"], info["land"]), ("none", "none"))

    def test_current_and_use_are_for_repositories_only(self):
        for args in (["current"], ["use", "1"], ["status", "1", "done"], ["landing", "auto", "--plan", "1"]):
            result = self.run_plan(*args)
            self.assertEqual(result.returncode, 1, args)
            self.assertIn("plan.py:", result.stderr)


if __name__ == "__main__":
    unittest.main()
