"""transplant in a farm whose plans live in its plan store (hal2 plan 0409 step 9): the target's model and effort come
from its current plan's `run:` line in the store (the plan rendered outside the tree). Skipped without a hal2-cli-plans
that has the store home."""

import json
import re
import sys
import unittest
from pathlib import Path

import transplant

sys.path.append(str(Path(transplant.planread.__file__).parent))  # the plan skill's scripts
from store_testkit import DEBUG, StoreFarm  # noqa: E402

PLAN = Path(transplant.planread.__file__).parent / "plan.py"


@unittest.skipUnless(DEBUG, "no hal2-cli-plans with the store home (cargo build -p hal2-cli-plans)")
class TransplantInTheStore(StoreFarm, unittest.TestCase):
    def test_the_targets_run_line_is_read_from_the_store(self):
        self.assertEqual(transplant.plan_run(self.repo), (None, None))
        self.run_ok(sys.executable, str(PLAN), "new", "Moved plan", "--goal", "Run where it lands")
        edit = json.loads(self.run_ok(sys.executable, str(PLAN), "edit"))
        plan = Path(edit["dir"]) / "plan.md"
        text = plan.read_text()
        self.assertRegex(text, r"(?m)^run: ")
        plan.write_text(re.sub(r"(?m)^run: .*$", "run: sonnet high 1m", text, count=1))
        self.run_ok(sys.executable, str(PLAN), "apply")
        self.assertEqual(transplant.plan_run(self.repo), ("sonnet[1m]", "high"))
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
