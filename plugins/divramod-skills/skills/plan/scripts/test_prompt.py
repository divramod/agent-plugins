"""plan.py prompt (prompt.py, plan 0016 step 3): the Agent call that runs one step in one subagent."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import prompt

SCRIPT = Path(__file__).resolve().parent / "plan.py"

RECORD = """---
type: Plan
schema: 1
id: 3
title: "Demo"
description: "A demo plan."
status: open
landing: auto
run: claude-opus-5-5 max 1m
created: 2026-10-10
---

# Plan 0003: Demo

## Steps

| # | Step | Done when | Model | Effort | Window | Size | Status |
|---|---|---|---|---|---|---|---|
| 1 | `session.py`: the live model, effort and window | `python3 -m unittest` passes | sonnet | high | 1m | 120k | next |
| 2 | Steps run in subagents: `plan.py prompt <n>` prints the call | prompt prints it | opus | xhigh | 1m | 200k | |
| 3 | Write the UATs: `uat.md` | `plan.py current` shows `uat` | sonnet | medium | 1m | 100k | |
| 4 | old work | done before | haiku | low | 200k | 40k | done |
"""

LEGACY = """# Plan 0002: old plan

Run: opus[1m] high

| # | Step | Done when | Status |
|---|---|---|---|
| 1 | one thing | it works | next |
| 2 | two | it works | |
"""

TASK = "# Step {n}: x\n\n## Task\n\nChange the thing in foo.py.\n\nDone when: it works\n"


class PromptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "repo"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.record = self.write("0003-demo", RECORD)
        (self.record.parent / "decisions.md").write_text("# Decisions\n")
        (self.root / "AGENTS.md").write_text("# rules\n")
        (self.root / "plans" / "CURRENT_PLAN").write_text("0003-demo\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, slug: str, text: str) -> Path:
        path = self.root / "plans" / slug / "plan.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def task(self, plan: Path, n: str, text: str = "") -> Path:
        step = plan.parent / "steps" / f"{n}.md"
        step.parent.mkdir(exist_ok=True)
        step.write_text(text or TASK.format(n=n))
        return step

    def run_plan(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "prompt", *args],
                              capture_output=True, text=True)

    def call(self, *args) -> dict:
        out = self.run_plan(*args)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def refused(self, *args) -> str:
        out = self.run_plan(*args)
        self.assertEqual(out.returncode, 1, out.stdout)
        return out.stderr

    def test_a_record_row_prints_the_agent_call(self):
        self.task(self.record, "1")

        call = self.call("1")

        self.assertEqual(list(call), ["description", "model", "effort", "run_in_background", "prompt"])
        self.assertEqual(call["description"], "Plan 0003 row 1: session.py: the live model")
        self.assertEqual((call["model"], call["effort"], call["run_in_background"]), ("sonnet", "high", True))
        text = call["prompt"]
        self.assertIn("step 1 of plan 0003 in the repo repository", text)
        self.assertIn(f"Work only in the git worktree {self.root}.", text)
        self.assertIn("plans/0003-demo/plan.md (its row 1 and its Context)", text)
        self.assertIn("your task plans/0003-demo/steps/1.md", text)
        self.assertIn("plans/0003-demo/decisions.md (decided: never re-decide them)", text)
        self.assertIn("The repo's rules: AGENTS.md.", text)
        self.assertIn("never commit, push, land or change git state, and never edit plan.md", text)
        self.assertIn("`## Approach`", text)
        self.assertIn("`## Notes`", text)
        self.assertIn("the other open steps: 2 Steps run in subagents; 3 Write the UATs)", text)
        self.assertNotIn("old work", text)  # a done step is not named
        self.assertIn("done-when (`python3 -m unittest` passes)", text)
        self.assertIn("at most 15 lines", text)

    def test_the_prompt_forbids_printing_the_environment(self):
        self.task(self.record, "1")

        text = self.call("1")["prompt"]

        self.assertIn("Never print the whole environment (`env`, `printenv`, `set`, `export -p`): it holds secrets", text)
        self.assertIn("read one variable by name", text)

    def test_part_names_the_retry(self):
        self.task(self.record, "2")

        call = self.call("2", "--part", "2")

        self.assertEqual(call["description"], "Plan 0003 row 2 part 2: Steps run in subagents")
        self.assertIn("This is part 2 of the step", call["prompt"])
        self.assertIn("counts the retries from 2", self.refused("2", "--part", "1"))

    def test_model_and_effort_override_the_row(self):
        self.task(self.record, "1")

        call = self.call("1", "--model", "claude-opus-5-5[1m]", "--effort", "max")

        self.assertEqual((call["model"], call["effort"]), ("opus", "max"))
        self.assertIn("none of haiku, sonnet, opus, fable", self.refused("1", "--model", "gpt-5"))
        self.assertEqual(self.run_plan("1", "--effort", "huge").returncode, 2)

    def test_a_step_file_without_a_written_task_is_refused(self):
        self.assertIn("steps/1.md has no written `## Task`", self.refused("1"))
        self.task(self.record, "1", "# Step 1: x\n\n## Task\n\n<what to change: the files and packages, the approach, "
                                    "what the step must not touch>\n\nDone when: it works\n")
        self.assertIn("`plan.py status 1 next` scaffolds", self.refused("1"))
        self.task(self.record, "1", "# Step 1: x\n\n## Task\n\nDone when: it works\n")
        self.assertIn("no written `## Task`", self.refused("1"))
        self.assertIn("no step '9'", self.refused("9"))

    def test_a_scaffolded_step_file_names_its_size_and_is_refused_until_written(self):
        self.record.write_text(RECORD.replace("| 120k | next |", "| 120k | |"))
        out = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "status", "1", "next"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        step = self.root / json.loads(out.stdout)["step_file"]

        self.assertIn("\n\nSize: 120k of 1m\nDone when: `python3 -m unittest` passes\n", step.read_text())
        self.assertIn("`plan.py status 1 next` scaffolds", self.refused("1"))
        step.write_text(step.read_text().replace("<what to change", "Change foo.py.\n<what to change"))
        self.assertEqual(self.call("1")["model"], "sonnet")

    def test_a_record_row_failing_the_sizing_is_refused(self):
        self.task(self.record, "1")
        self.record.write_text(RECORD.replace("| sonnet | high | 1m | 120k |", "| sonnet | high | 200k | 120k |"))
        error = self.refused("1")
        self.assertIn("step 1: Size 120k is over 35% of Window 200k", error)
        self.assertIn("plan-steps-sized", error)

        self.record.write_text(RECORD.replace("| sonnet | high | 1m | 120k |", "| opus[1m] | high | 1m | 120k |"))
        self.assertIn("Model 'opus[1m]' is none of", self.refused("1"))

        rows = [line for line in RECORD.splitlines(keepends=True) if not line.startswith("| ")]
        self.record.write_text("".join(rows).rstrip("\n").removesuffix("|---|---|---|---|---|---|---|---|") +
                               "| # | Step | Done when | Model | Effort | Size | Status |\n|---|---|---|---|---|---|---|\n"
                               "| 1 | one | it works | sonnet | high | 120k | next |\n")
        self.assertIn("no column Window: run `plan.py migrate`", self.refused("1"))

    def test_a_legacy_row_takes_run_and_maps_the_model_to_its_alias(self):
        legacy = self.write("0002-old-plan", LEGACY)
        self.task(legacy, "1")

        call = self.call("1", "--plan", "2")

        self.assertEqual(call["description"], "Plan 0002 row 1: one thing")
        self.assertEqual((call["model"], call["effort"]), ("opus", "high"))  # `Run: opus[1m] high`
        self.assertNotIn("decisions", call["prompt"])  # the legacy plan has none

    def test_a_legacy_plan_without_run_leaves_model_and_effort_to_the_agent(self):
        legacy = self.write("0002-old-plan", LEGACY.replace("Run: opus[1m] high\n", ""))
        self.task(legacy, "1")

        call = self.call("1", "--plan", "2")

        self.assertNotIn("model", call)
        self.assertNotIn("effort", call)
        legacy.write_text(LEGACY.replace("opus[1m]", "gpt-5"))
        self.assertIn("model 'gpt-5' is none of", self.refused("1", "--plan", "2"))
        self.assertEqual(self.call("1", "--plan", "2", "--model", "sonnet")["model"], "sonnet")

    def test_the_fixture_from_plan_new_prints_row_1(self):
        out = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "new", "fresh work"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        plan = self.root / json.loads(out.stdout)["path"]
        self.task(plan, "1")

        call = self.call("1")

        self.assertTrue(call["description"].startswith(f"Plan {plan.parent.name[:4]} row 1: "))
        self.assertEqual((call["model"], call["effort"]), ("opus", "medium"))  # the template's row 1


class ShortTitleTest(unittest.TestCase):
    def test_the_first_clause_without_backticks(self):
        cases = {
            "Steps run in subagents: `plan.py prompt <n>` prints the Agent call": "Steps run in subagents",
            "`session.py`: the session's live model, effort and window": "session.py: the session's live model",
            "grill: the autogrill sets Model, Effort, Window": "grill: the autogrill sets Model",
            "farmer, create-worktree-session: coordinator sentence": "farmer, create-worktree-session",
            "Write the UATs: `uat.md` beside this file": "Write the UATs",
            "a very long first clause that goes on and on and on": "a very long first clause that",
            "one": "one",
        }
        for step, title in cases.items():
            self.assertEqual(prompt.short_title(step), title, step)

    def test_alias(self):
        for model, name in (("opus[1m]", "opus"), ("claude-sonnet-5-5", "sonnet"), ("Haiku 4.5", "haiku"),
                            ("fable", "fable")):
            self.assertEqual(prompt.alias(model), name)
        with self.assertRaises(prompt.PromptError):
            prompt.alias("gpt-5")


if __name__ == "__main__":
    unittest.main()
