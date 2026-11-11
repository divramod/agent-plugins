import unittest

import testkit
from checks import readonly_root


class ReadonlyRootTest(unittest.TestCase):
    def test_tmp_and_the_next_cache(self):
        found = readonly_root.run(testkit.ctx(inspect={"frameworks": ["next"]}))
        self.assertEqual(len(found), 2)

    def test_declared_paths_pass(self):
        ctx = testkit.ctx(container={"writable": ["/tmp", "/app/.next/cache"]}, inspect={"frameworks": ["next"]})
        self.assertEqual(readonly_root.run(ctx), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(readonly_root.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
