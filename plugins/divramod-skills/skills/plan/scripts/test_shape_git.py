"""`plan.py subplan start|finish <NN>` (hal2 plan 0376, row 8, design A9) in a temp git repository named `07`: start
switches to the side branch `07-NN` (made from `07`), refuses a dirty tree; finish refuses open steps, switches back
to `07` and merges the side branch `--no-ff`."""
import unittest

from shape_testing import TempPlan


class SubplanBranchTest(TempPlan):
    def setUp(self):
        super().setUp()
        self.folder = self.new("deploy the hub")
        self.commit_all("plan")

    def branch(self) -> str:
        return self.git("branch", "--show-current").strip()

    def test_start_and_finish_build_the_subplan_on_its_side_branch(self):
        info = self.plan("subplan", "start", "1")
        self.assertEqual((info["branch"], info["created"], self.branch()), ("07-01", True, "07-01"))
        self.assertFalse(self.plan("subplan", "start", "01")["switched"])
        self.assertIn("is not done", self.refused("subplan", "finish", "1"))
        self.assertEqual(self.branch(), "07-01")
        for ref in ("01.01", "01.02"):
            self.plan("status", ref, "done")
        self.assertIn("uncommitted", self.refused("subplan", "finish", "1"))
        self.commit_all("steps done")
        info = self.plan("subplan", "finish", "1")
        self.assertEqual((info["merged"], info["into"], self.branch()), ("07-01", "07", "07"))
        parents = self.git("log", "-1", "--format=%P").split()
        self.assertEqual(len(parents), 2)
        self.assertIn("Plan: 0001-deploy-the-hub\nStep: 2/2", self.git("log", "-1", "--format=%B"))

    def test_start_refuses_a_dirty_tree_and_another_branch(self):
        (self.folder / "plan.md").write_text((self.folder / "plan.md").read_text() + "\nmore\n")
        self.assertIn("uncommitted", self.refused("subplan", "start", "1"))
        self.git("checkout", "-q", "--", ".")
        self.git("switch", "-q", "-c", "other")
        self.assertIn("field's branch `07`", self.refused("subplan", "start", "1"))
        self.assertIn("no side branch", self.refused("subplan", "finish", "1"))


if __name__ == "__main__":
    unittest.main()
