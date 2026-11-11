"""D17: a check without its test fails here; every check is well formed."""

import unittest
from pathlib import Path

import checks

HERE = Path(__file__).resolve().parent


class ChecksTest(unittest.TestCase):
    def test_every_check_has_a_test(self):
        for module in checks.modules():
            name = module.__name__.rsplit(".", 1)[1]
            with self.subTest(check=name):
                self.assertTrue((HERE / f"test_check_{name}.py").is_file(), f"{name} has no test_check_{name}.py")

    def test_every_check_is_well_formed(self):
        slugs = []
        for module in checks.modules():
            with self.subTest(check=module.__name__):
                self.assertEqual(module.SLUG.replace("-", "_"), module.__name__.rsplit(".", 1)[1])
                self.assertTrue(module.WHY)
                self.assertIsInstance(module.run({"site": "x", "container": {}, "inspect": None}), list)
                slugs.append(module.SLUG)
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_every_check_is_in_the_problem_log(self):
        log = (HERE.parent / "references/problems.md").read_text()
        for module in checks.modules():
            self.assertIn(f"`{module.SLUG}`", log)


if __name__ == "__main__":
    unittest.main()
