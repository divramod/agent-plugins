"""milestone.py and plan.py milestone (plan 0593 step 3): the row forms, `milestone --after`, the hitch relayed from
hal2-plans, and a row `after milestone <n>` waiting in a parallel plan."""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import milestone
import parallel
import testkit

SCRIPT = Path(__file__).resolve().parent / "plan.py"
PLAN = """---
type: Plan
schema: 1
id: 5
title: "ms"
description: "d"
status: open
landing: auto
run: claude-opus-5-5 medium 1m
created: 2026-11-03
---

# Plan 0005: ms

## Steps

| # | Step | Done when | Model | Effort | Window | Size | Status |
|---|---|---|---|---|---|---|---|
| 1 | one | ok | sonnet | medium | 1m | 10k | done |
| 2 | two | ok | sonnet | medium | 1m | 10k | |
| 3 | three | after milestone 1: ok | sonnet | medium | 1m | 10k | |
| 4 | four | after the landing: ok | sonnet | medium | 1m | 10k | |
"""
FAKE = """#!/bin/sh
echo '{"progress":{"schema":1,"hitch":{"kind":"partial","n":null,"of":0,"open_before":["2"],"after_landing_open":1}},"problems":["rule problem"]}'
"""


class MilestoneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        testkit.init_repo(self.root)
        self.path = self.root / "plans" / "0005-ms" / "plan.md"
        self.path.parent.mkdir(parents=True)
        self.path.write_text(PLAN)
        (self.root / "plans" / "CURRENT_PLAN").write_text("0005-ms\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_plan(self, *args, cli: str | None = None):
        env = {**os.environ, "HAL2_CLI_PLANS": cli or str(self.root / "no-such-cli")}
        return testkit.run(SCRIPT, ["--root", str(self.root), *args], env=env, cwd=self.root)

    def plan(self, *args, cli=None) -> dict:
        out = self.run_plan(*args, cli=cli)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_row_forms(self):
        self.assertEqual(milestone.number("**Milestone 2**: land"), 2)
        self.assertIsNone(milestone.number("the milestone 2"))
        self.assertEqual(milestone.after("After milestone 3: cargo test"), 3)
        self.assertIsNone(milestone.after("after the landing: x"))

    def test_milestone_after_inserts_the_next_free_id_at_that_position(self):
        info = self.plan("milestone", "--after", "2", "--title", "the CLI lands")

        self.assertEqual(info["milestone"], {"step": "5", "n": 1})
        self.assertEqual([s["number"] for s in info["steps"]], ["1", "2", "5", "3", "4"])
        row = info["steps"][2]
        self.assertEqual((row["step"], row["milestone"]), ("Milestone 1: the CLI lands", 1))
        self.assertEqual(info["steps"][3]["after_milestone"], 1)
        self.assertEqual(info["problems"], [])  # the new row is sized: plan-steps-sized stays quiet

    def test_second_milestone_gets_the_next_number_and_ids_are_never_renumbered(self):
        self.plan("milestone", "--after", "2")
        info = self.plan("milestone", "--after", "3")

        self.assertEqual(info["milestone"], {"step": "6", "n": 2})
        self.assertEqual([s["number"] for s in info["steps"]], ["1", "2", "5", "3", "6", "4"])

    def test_a_milestone_that_would_not_rise_is_refused_and_writes_nothing(self):
        self.plan("milestone", "--after", "3")
        before = self.path.read_text()

        out = self.run_plan("milestone", "--after", "1")

        self.assertEqual(out.returncode, 1)
        self.assertIn("never renumbered", out.stderr)
        self.assertEqual(self.path.read_text(), before)

    def test_unknown_step_is_refused(self):
        out = self.run_plan("milestone", "--after", "9")

        self.assertEqual(out.returncode, 1)
        self.assertIn("no step '9'", out.stderr)

    def test_hitch_and_rule_problems_come_from_hal2_plans(self):
        fake = self.root / "fake-cli"
        fake.write_text(FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

        info = self.plan("current", cli=str(fake))

        self.assertEqual(info["hitch"]["kind"], "partial")
        self.assertEqual(info["hitch"]["open_before"], ["2"])
        self.assertIn("rule problem", info["problems"])

    def test_without_the_cli_the_hitch_is_null_with_a_note(self):
        info = self.plan("current")

        self.assertIsNone(info["hitch"])
        self.assertIn("hal2-cli-plans", info["hitch_note"])

    def test_an_after_milestone_row_waits_while_the_milestone_is_open(self):
        steps = [
            {"number": "1", "step": "Milestone 1: land", "status": "", "needs": [], "touches": ["@land"],
             "after_landing": False, "milestone": 1, "after_milestone": None},
            {"number": "2", "step": "next", "status": "", "needs": [], "touches": [],
             "after_landing": False, "milestone": None, "after_milestone": 1},
        ]
        ready, waiting = parallel.schedule(steps, {})
        self.assertEqual([s["number"] for s in ready], ["1"])
        self.assertEqual(waiting[0]["why"], "waits for Milestone 1 in the barn")

        steps[0]["status"] = "done"
        self.assertEqual([s["number"] for s in parallel.schedule(steps, {})[0]], ["2"])

    def test_a_blank_line_before_the_milestone_row_keeps_the_plan_open(self):
        """Plan 0695 row 53: rows 1-2 done, Milestone row 3 after a blank line, row 4 open."""
        text = PLAN.replace("| 3 | three | after milestone 1: ok", "\n| 3 | Milestone 1: land | the rows above are landed")
        text = text.replace("| 4 | four | after the landing: ok", "| 4 | four | ok")
        self.path.write_text(text)
        (self.path.parent / "decisions.md").write_text("---\ntype: Decisions\nstatus: open\n---\n")
        self.plan("status", "2", "done")

        after = self.path.read_text()
        self.assertIn("status: open", after)
        self.assertNotIn("finished", after.lower())
        self.assertIn("status: open", (self.path.parent / "decisions.md").read_text())
        info = self.plan("current")
        self.assertEqual((info["done"], info["total"]), (2, 4))
        self.assertEqual([s["number"] for s in info["steps"]], ["1", "2", "3", "4"])


if __name__ == "__main__":
    unittest.main()
