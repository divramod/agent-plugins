"""`plan.py check` and hal2's questions checker (hal2 plan 0329 step 4): an open question of the agent that is not in
the Q form is a problem ending in `(questions-q-form)`; without the CLI one advisory line and no failure.

The CLI is faked by a stub (qstub.py); one test runs the real binary when `$HAL2_CLI_PLANS` or PATH has one.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "plan.py"
sys.path.insert(0, str(HERE))

import qcheck  # noqa: E402
import qstub  # noqa: E402

INLINE = ("\n## Q1 · 2026-10-14 · agent · open\n\n**Q:** Where are the apps built? a) (Recommended) by hand b) in "
          "every landing c) never\n")
PROBLEM = {"n": 1, "message": "its options a) b) c) are inline in the question; the Q form puts each on its own line"}
LINE = ("plans/0001-tiny/questions.md: Q1: its options a) b) c) are inline in the question; the Q form puts each on "
        "its own line (questions-q-form)")


class QCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.bin = self.root.parent / (self.root.name + "-bin")
        self.bin.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "new", "Tiny"],
                                capture_output=True, text=True, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.plan = self.root / json.loads(result.stdout)["path"]
        self.plan.write_text(re.sub(r"^- (Out|Proof): <.*>$", r"- \1: written", self.plan.read_text(), flags=re.M)
                             .replace("- Seed: <seedbag>#<n>\n", ""))
        self.store = self.plan.parent / "questions.md"

    def tearDown(self):
        self.tmp.cleanup()
        for f in self.bin.iterdir():
            f.unlink()
        self.bin.rmdir()

    def check(self, cli: str | None, *args) -> tuple[int, list[str]]:
        """`plan.py check` with the questions CLI pinned (None: none); the records checker lines are dropped."""
        env = {**os.environ, qcheck.ENV: cli or str(self.bin / "none")}
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "check", *args],
                                capture_output=True, text=True, env=env, cwd=self.root)
        lines = [l for l in result.stdout.splitlines() if not l.startswith(("ok", "records unchecked"))]
        return result.returncode, lines

    def test_an_open_question_not_in_the_q_form_is_a_problem_ending_in_the_rule(self):
        self.store.write_text(self.store.read_text() + INLINE)
        cli = qstub.write(self.bin, [PROBLEM], 1)
        self.assertEqual(self.check(cli), (1, [LINE]))
        self.assertEqual(self.check(cli, str(self.plan.parent)), (1, [LINE]))
        args = (self.bin / "args").read_text().splitlines()[-1]
        self.assertEqual(args, f"questions check --json --store {self.store}")

    def test_a_clean_store_passes(self):
        self.assertEqual(self.check(qstub.write(self.bin)), (0, []))

    def test_without_the_cli_the_questions_are_unchecked_and_pass(self):
        self.store.write_text(self.store.read_text() + INLINE)
        self.assertEqual(self.check(None), (0, [qcheck.NOT_INSTALLED]))

    def test_an_older_cli_without_the_command_is_unchecked_and_passes(self):
        cli = qstub.write(self.bin, out="hal2-cli-plans: unknown command", code=2)
        self.assertEqual(self.check(cli), (0, [qcheck.TOO_OLD]))

    def test_a_legacy_plan_is_not_checked(self):
        legacy = self.root / "plans" / "0002-old"
        legacy.mkdir()
        (legacy / "plan.md").write_text("# Plan 0002: old\n\n| # | Step | Status |\n|---|---|---|\n| 1 | x | done |\n")
        (legacy / "questions.md").write_text(INLINE)
        cli = qstub.write(self.bin)
        self.assertEqual(self.check(cli), (0, []))
        self.assertNotIn("0002-old", (self.bin / "args").read_text())

    def test_the_real_cli_reports_the_inline_options_of_an_open_question(self):
        cli = qcheck.binary()
        probe = subprocess.run([cli, "questions", "check", "--store", str(self.store)], capture_output=True) \
            if cli else None
        if probe is None or probe.returncode not in (0, 1):
            self.skipTest("no hal2-cli-plans with `questions check` (set $HAL2_CLI_PLANS to the built binary)")
        self.assertEqual(self.check(cli), (0, []))
        self.store.write_text(self.store.read_text() + INLINE)
        self.assertEqual(self.check(cli), (1, [LINE]))


if __name__ == "__main__":
    unittest.main()
