"""The merge-to-main boss in a farm whose plans live in its plan store (hal2 plan 0409 step 9): an orphan's plan
handoff is found in the store (the plan rendered outside the tree), not in a plans/ folder. Skipped without a
hal2-cli-plans that has the store home."""

import sys
import unittest
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import boss

sys.path.append(str(Path(boss.planread.__file__).parent))  # the plan skill's scripts
from store_testkit import DEBUG, StoreFarm  # noqa: E402

PLAN = Path(boss.planread.__file__).parent / "plan.py"


@unittest.skipUnless(DEBUG, "no hal2-cli-plans with the store home (cargo build -p hal2-cli-plans)")
class BossInTheStore(StoreFarm, unittest.TestCase):
    def test_a_plans_handoff_in_the_store_counts(self):
        self.run_ok(sys.executable, str(PLAN), "new", "Orphan work", "--goal", "Left by its session")
        self.assertIn("handoff.md", self.rendered("1"))  # plan.py new writes the plan's handoff
        self.assertTrue(boss.has_handoff(self.repo, "0001-orphan-work"))
        self.assertFalse(boss.has_handoff(self.repo, "0002-none"))
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
