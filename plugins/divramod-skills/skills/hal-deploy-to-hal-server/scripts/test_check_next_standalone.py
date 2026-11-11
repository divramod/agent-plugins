import unittest

import testkit
from checks import next_standalone


class NextStandaloneTest(unittest.TestCase):
    def test_a_plain_config_is_found_and_standalone_is_not(self):
        plain = testkit.ctx(inspect={"next_configs": [{"path": "web/next.config.ts", "standalone": False}]})
        self.assertEqual([f["severity"] for f in next_standalone.run(plain)], ["warn"])
        good = testkit.ctx(inspect={"next_configs": [{"path": "web/next.config.ts", "standalone": True}]})
        self.assertEqual(next_standalone.run(good), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(next_standalone.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
