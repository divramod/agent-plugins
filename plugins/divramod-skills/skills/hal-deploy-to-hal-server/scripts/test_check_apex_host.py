import unittest

import testkit
from checks import apex_host


class ApexHostTest(unittest.TestCase):
    def test_the_apex_itself_is_an_error(self):
        found = apex_host.run({"site": "s", "container": {}, "inspect": None, "hosts": ["@"], "domain": "divramod.me"})
        self.assertEqual(found[0]["severity"], "error")

    def test_a_repository_named_after_the_zone(self):
        ctx = testkit.ctx(inspect={"name": "divramod.me", "remote_name": "divramod-me"}, hosts=["www"], domain="divramod.me")
        self.assertIn("www.divramod.me", apex_host.run(ctx)[0]["detail"])

    def test_another_repository(self):
        ctx = testkit.ctx(inspect={"name": "accounter", "remote_name": "steueragenten"}, hosts=["a"], domain="divramod.me")
        self.assertEqual(apex_host.run(ctx), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(apex_host.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
