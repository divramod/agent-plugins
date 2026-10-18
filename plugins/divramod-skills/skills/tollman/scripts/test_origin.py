"""The origin trailers of the tollman's commits (hal2 plan 0355, D2)."""
import unittest

import origin


class OriginTest(unittest.TestCase):
    def test_a_train_names_every_car_in_order_and_each_plan_once(self):
        self.assertEqual(origin.trailers(["02", "03", "27", "03"], ["0355-commit-standards", "0349-ci-adaptions"]),
                         "Worktree: 02, 03, 27\nPlan: 0355-commit-standards\nPlan: 0349-ci-adaptions")

    def test_only_a_numbered_plan_is_a_plan_trailer(self):
        self.assertEqual(origin.trailers(["09"], ["shots/3/fix-it", "", "0001-x"]), "Worktree: 09\nPlan: 0001-x")

    def test_the_yard_is_a_worktree_name(self):
        self.assertEqual(origin.trailers([origin.YARD]), "Worktree: main")

    def test_nothing_known_is_no_trailer(self):
        self.assertEqual(origin.trailers([]), "")


if __name__ == "__main__":
    unittest.main()
