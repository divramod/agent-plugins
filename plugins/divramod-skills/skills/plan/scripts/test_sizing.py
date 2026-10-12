"""The step sizing of record plans (plan 0016 step 2): the `plan-steps-sized` check, `plan.py run`, `plan.py migrate`
and the live values `new` writes into `run`.

Every run is isolated from the session running the tests: its own HOME, no session id, a `ps` that shows no
`claude`, and no hal2 records checker (the sizing check is plan.py's own and runs without it).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "plan.py"
sys.path.insert(0, str(HERE))

import checker  # noqa: E402
import sizing  # noqa: E402

HEADER = "| # | Step | Done when | Model | Effort | Window | Size | Status |\n|---|---|---|---|---|---|---|---|\n"


def record(rows: str, run: str = "opus max 1m", header: str = HEADER) -> str:
    return f"---\ntype: Plan\nschema: 1\nid: 1\nrun: {run}\nstatus: open\n---\n\n# Plan 0001: Demo\n\n## Steps\n\n{header}{rows}"


class SizingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        self.home = self.root / "home"
        (self.home / "bin").mkdir(parents=True)
        (self.home / "bin" / "ps").write_text("#!/bin/sh\n")
        (self.home / "bin" / "ps").chmod(0o755)
        self.live = {}

    def tearDown(self):
        self.tmp.cleanup()

    def env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
        env.update(HOME=str(self.home), PATH=f"{self.home / 'bin'}:{os.environ.get('PATH', '')}",
                   **{checker.ENV: str(self.root / "no-hal2-cli-records")}, **self.live)
        return env

    def run_plan(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                              capture_output=True, text=True, env=self.env())

    def plan(self, *args) -> dict:
        result = self.run_plan(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def write(self, text: str, slug: str = "0001-demo") -> Path:
        path = self.root / "plans" / slug / "plan.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        (self.root / "plans" / "CURRENT_PLAN").write_text(slug + "\n")
        return path

    def check(self) -> tuple[int, list[str]]:
        result = self.run_plan("check")
        lines = [l for l in result.stdout.splitlines() if not l.startswith(("ok: no plan number", "records unchecked"))]
        return result.returncode, lines

    def test_a_sized_plan_passes(self):
        self.write(record("| 1 | a | t | opus | high | 1m | 350k | next |\n| 2 | b | t | sonnet | low | 200k | 70k | |\n"))
        self.assertEqual(self.check(), (0, []))

    def test_an_open_row_without_window_is_refused(self):
        """The done-when of plan 0016 step 2: a fixture plan whose open row lacks Window."""
        self.write(record("| 1 | a | t | opus | high | 1m | 90k | done |\n| 2 | b | t | opus | high | | 90k | next |\n"))
        code, lines = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["plans/0001-demo/plan.md:16: step 2: Window '' is none of 200k, 1m (plan-steps-sized)"])
        header = "| # | Step | Done when | Model | Effort | Size | Status |\n|---|---|---|---|---|---|---|\n"
        self.write(record("| 1 | a | t | opus | high | 90k | next |\n", header=header))
        code, lines = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["plans/0001-demo/plan.md:13: the step table has no column Window: run `plan.py "
                                 "migrate` (plan-steps-sized)"])
        self.assertEqual(self.plan("current")["problems"], lines)

    def test_every_invalid_value_is_one_line(self):
        self.write(record("| 1 | a | t | claude-opus-5-5 | huge | 2m | ? | next |\n| 2 | b | t | opus | max | 200k | 71k | |\n"
                          "| 3 | c | t | opus | max | 1m | 351k | |\n| 4 | d | t | opus | max | 1m | lots | |\n"))
        code, lines = self.check()
        self.assertEqual(code, 1)
        messages = [l.split(": ", 1)[1] for l in lines]
        self.assertEqual(messages, [
            "step 1: Model 'claude-opus-5-5' is none of haiku, sonnet, opus, fable (plan-steps-sized)",
            "step 1: Effort 'huge' is none of low, medium, high, xhigh, max (plan-steps-sized)",
            "step 1: Window '2m' is none of 200k, 1m (plan-steps-sized)",
            "step 1: Size '?' is not estimated: the step's peak context, e.g. 150k (the autogrill sizes it) "
            "(plan-steps-sized)",
            "step 2: Size 71k is over 35% of Window 200k (70k): split the step (plan-steps-sized)",
            "step 3: Size 351k is over 35% of Window 1m (350k): split the step (plan-steps-sized)",
            "step 4: Size 'lots' is no <n>k or <n>m (plan-steps-sized)",
        ])

    def test_run_needs_three_valid_words_while_a_row_is_open(self):
        rows = "| 1 | a | t | opus | high | 1m | 90k | next |\n"
        self.write(record(rows, run="claude-opus-5-5 max"))
        code, lines = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["plans/0001-demo/plan.md:5: run 'claude-opus-5-5 max' needs three words, <model> "
                                 "<effort> <window> (e.g. `opus max 1m`; `plan.py run --sync`) (plan-steps-sized)"])
        self.write(record(rows, run="claude-opus-5-5 max 1m"))
        self.assertEqual(self.check(), (0, []))
        self.write(record(rows, run="gpt max 1m"))
        self.assertIn("run's model 'gpt'", self.check()[1][0])

    def test_done_rows_finished_plans_and_legacy_plans_pass(self):
        # Plan 0015's shape: every row done, the two-word `run`, no Size column.
        header = "| # | Step | Done when | Model | Effort | Window | Status |\n|---|---|---|---|---|---|---|\n"
        self.write(record("| 1 | a | t | | | | done |\n", run="claude-opus-5-5 max", header=header))
        self.write("# Plan 0002: old\n\nRun: opus medium\n\n| # | Step | Status |\n|---|---|---|\n| 1 | x | next |\n",
                   slug="0002-old")
        self.assertEqual(self.check(), (0, []))

    def test_new_writes_the_live_values_into_run_else_the_templates(self):
        info = self.plan("new", "deploy the hub")
        text = (self.root / info["path"]).read_text()
        self.assertIn("\nrun: opus medium 1m\n", text)
        self.assertIn("| # | Step | Done when | Model | Effort | Window | Size | Status |", text)
        step = info["next"]
        self.assertEqual((step["model"], step["effort"], step["window"], step["size"]), ("opus", "medium", "1m", "150k"))
        self.assertEqual(info["problems"], [])
        self.live = {"ANTHROPIC_MODEL": "claude-opus-5-5[1m]", "CLAUDE_EFFORT": "max"}
        info = self.plan("new", "deploy the nodes")
        self.assertIn("\nrun: claude-opus-5-5 max 1m\n", (self.root / info["path"]).read_text())
        self.assertEqual(self.check(), (0, []))

    def test_run_check_sync_and_explicit_values(self):
        path = self.write(record("| 1 | a | t | opus | high | 1m | 90k | next |\n", run="opus max 1m"))
        self.live = {"ANTHROPIC_MODEL": "Opus 5.5 (1M context)", "CLAUDE_EFFORT": "medium"}
        result = self.plan("run", "--check")
        self.assertEqual(result["drift"], {"effort": {"session": "medium", "plan": "max"}})
        self.assertEqual((result["run"], result["live"]["effort"]), ("opus max 1m", "medium"))
        self.assertIn("run: opus max 1m\n", path.read_text(), "--check never writes")
        result = self.plan("run", "--sync")
        self.assertEqual((result["run"], result["before"], result["drift"]), ("claude-opus-5-5 medium 1m", "opus max 1m", {}))
        result = self.plan("run", "--effort", "xhigh", "--window", "200k")
        self.assertEqual(result["run"], "claude-opus-5-5 xhigh 200k")
        self.assertEqual(self.plan("run", "--model", "sonnet[1m]")["run"], "sonnet xhigh 200k")
        for args in ((), ("--sync", "--effort", "max"), ("--model", "gpt-9")):
            result = self.run_plan("run", *args)
            self.assertEqual(result.returncode, 1, args)
        legacy = self.write("# Plan 0002: old\n\nRun: opus medium\n\n## Steps\n", slug="0002-old")
        self.plan("run", "--sync", "--plan", "2")
        self.assertIn("Run: claude-opus-5-5 medium 1m\n", legacy.read_text())

    def test_migrate_adds_the_columns_and_fills_the_open_rows(self):
        header = "| # | Step | Done when | Model | Effort | Status |\n|---|---|---|---|---|---|\n"
        path = self.write(record("| 1 | a | t | | | done |\n| 2 | b | t | | | next |\n| 3 | c | t | sonnet | low | |\n",
                                 run="claude-opus-5-5 max", header=header))
        self.live = {"CLAUDE_EFFORT": "high"}
        result = self.plan("migrate")
        self.assertTrue(result["migrated"])
        text = path.read_text()
        self.assertIn("\nrun: claude-opus-5-5 high 1m\n", text)
        self.assertIn("| # | Step | Done when | Model | Effort | Window | Size | Status |\n"
                      "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                      "| 1 | a | t |  |  |  |  | done |\n"
                      "| 2 | b | t | opus | max | 1m | ? | next |\n"
                      "| 3 | c | t | sonnet | low | 1m | ? |  |\n", text)
        code, lines = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("Size '?' is not estimated" in l for l in lines))
        self.plan("migrate")
        self.assertIn("| 2 | b | t | opus | max | 1m | ? | next |\n", path.read_text(), "migrate twice changes nothing")
        legacy = "# Plan 0002: old\n\n| # | Step | Status |\n|---|---|---|\n| 1 | x | next |\n"
        self.write(legacy, slug="0002-old")
        self.assertFalse(self.plan("migrate", "--plan", "2")["migrated"])
        self.assertEqual((self.root / "plans" / "0002-old" / "plan.md").read_text(), legacy)

    def test_migrate_puts_window_after_effort_in_a_parallel_table(self):
        self.assertEqual(sizing.migrate_header(["#", "Step", "Needs", "Done when", "Model", "Effort", "Who", "Status"]),
                         ["#", "Step", "Needs", "Done when", "Model", "Effort", "Window", "Size", "Who", "Status"])
        self.assertEqual(sizing.migrate_header(["#", "Step", "Status"]),
                         ["#", "Step", "Model", "Effort", "Window", "Size", "Status"])
        self.assertEqual(sizing.window_of_model("claude-opus-4-1"), "200k")
        self.assertEqual(sizing.window_of_model("opus"), "1m")


if __name__ == "__main__":
    unittest.main()
