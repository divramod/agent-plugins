import unittest

import testkit
from checks import postgres_needed


class PostgresNeededTest(unittest.TestCase):
    def test_a_driver_warns_and_no_egress_is_an_error(self):
        self.assertEqual(postgres_needed.run(testkit.ctx(inspect={"drivers": ["pg"]}))[0]["severity"], "warn")
        closed = testkit.ctx(container={"egress": False}, inspect={"drivers": ["pg"]})
        self.assertEqual(postgres_needed.run(closed)[0]["severity"], "error")

    def test_no_driver(self):
        self.assertEqual(postgres_needed.run(testkit.ctx()), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(postgres_needed.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
