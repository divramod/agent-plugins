import unittest

import testkit
from checks import neon_driver


class NeonDriverTest(unittest.TestCase):
    def test_the_driver_and_another(self):
        self.assertEqual(len(neon_driver.run(testkit.ctx(inspect={"drivers": ["@neondatabase/serverless"]}))), 1)
        self.assertEqual(neon_driver.run(testkit.ctx(inspect={"drivers": ["pg"]})), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(neon_driver.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
