"""get-state in a farm whose plans live in its plan store (hal2 plan 0409 step 9): a field's plan (its steps and
description) and the farmer page's ledgers (questions and decisions) are read through hal2-cli-plans, the plan rendered
outside the tree, never from a plans/ folder. Skipped without a hal2-cli-plans that has the store home."""

import json
import sys
import unittest
from pathlib import Path

import ledger_sources
import state_sources

sys.path.append(str(state_sources.sibling("plan", __file__) / "scripts"))
from store_testkit import DEBUG, StoreFarm  # noqa: E402

PLAN = state_sources.sibling("plan", __file__) / "scripts" / "plan.py"
DECISION = ("\n## D1 · 2026-10-20 · user · in-force\n\n**D:** the store is the plans' home\n"
            "**Words:** \"keep it out of the tree\"\n")


@unittest.skipUnless(DEBUG, "no hal2-cli-plans with the store home (cargo build -p hal2-cli-plans)")
class StateInTheStore(StoreFarm, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.cli("new", "Store state", "--goal", "Read from the store", "--no-current")
        self.cli("questions", "add", "Which home?", "--option", "store", "--option", "files", "--option", "both",
                 "--plan", "1")
        edit = json.loads(self.run_ok(sys.executable, str(PLAN), "edit", "--plan", "1"))
        decisions = Path(edit["dir"]) / "decisions.md"
        decisions.write_text(decisions.read_text() + DECISION)
        self.run_ok(sys.executable, str(PLAN), "apply")

    def test_a_fields_plan_comes_from_the_store(self):
        found = state_sources.plan_of(self.repo, "0001-store-state")
        self.assertEqual((found["plan_number"], found["plan_slug"], found["steps_total"]), ("0001", "0001-store-state", 1))
        self.assertEqual(state_sources.open_questions(self.repo, "0001-store-state"), ["Q1"])
        self.assert_clean()

    def test_the_farmer_pages_ledgers_come_from_the_store(self):
        rows = [{"wt": "03", "path": str(self.repo), "plan": "0001-store-state"}]
        self.assertEqual([(q["n"], q["question"]) for q in ledger_sources.questions(rows)], [("Q1", "Which home?")])
        self.assertEqual([(d["n"], d["decision"]) for d in ledger_sources.decisions(rows)],
                         [("D1", "the store is the plans' home")])
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
