"""The farmer's plan reads in a farm whose plans live in its plan store (hal2 plan 0409 step 9): `decision check` reads
the asking field's plan, ledger and handoff, and a servant's marker its foreman's step table, from the store (the plan
rendered outside the tree). Skipped without a hal2-cli-plans that has the store home."""

import sys
import unittest
from pathlib import Path

import decision_check
import lead_marker

sys.path.append(str(Path(decision_check.planread.__file__).parent))  # the plan skill's scripts
from store_testkit import DEBUG, StoreFarm  # noqa: E402


@unittest.skipUnless(DEBUG, "no hal2-cli-plans with the store home (cargo build -p hal2-cli-plans)")
class FarmerInTheStore(StoreFarm, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.cli("new", "Farmer reads", "--goal", "The goal the farmer finds")  # CURRENT_PLAN names it

    def test_the_decision_check_reads_the_current_plan_from_the_store(self):
        texts = decision_check.checkout_texts(self.repo)
        self.assertTrue(any("The goal the farmer finds" in t for t in texts), texts)
        self.assertTrue(any(t.startswith("---\ntype: Decisions") for t in texts))
        self.assert_clean()

    def test_a_servants_foreman_plan_is_read_from_the_store(self):
        lead = {"slot": "02", "plan": "0001-farmer-reads", "step": "1"}
        self.assertEqual(lead_marker.foreman_over(self.repo, lead), (False, "plan 0001-farmer-reads of field 02 is open"))
        self.cli("status", "1", "1", "done")
        lead_marker.planread._DIRS.clear()  # a reader's copy is the process's: a new round renders again
        self.assertEqual(lead_marker.foreman_over(self.repo, lead), (True, "plan 0001-farmer-reads of field 02 is done"))


if __name__ == "__main__":
    unittest.main()
