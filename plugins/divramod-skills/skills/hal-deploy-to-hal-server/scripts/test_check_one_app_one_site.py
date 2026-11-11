import unittest

import testkit
from checks import one_app_one_site


class OneAppOneSiteTest(unittest.TestCase):
    def test_two_apps_and_one(self):
        two = one_app_one_site.run(testkit.ctx(inspect={"apps": ["apps/a", "apps/b"]}))
        self.assertIn("apps/b", two[0]["detail"])
        self.assertEqual(one_app_one_site.run(testkit.ctx(inspect={"apps": ["apps/a"]})), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(one_app_one_site.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
