import unittest

import testkit
from checks import build_context


class BuildContextTest(unittest.TestCase):
    def test_missing_sources_and_a_good_context(self):
        bad = {"workflow": "d.yml", "context": ".", "file": "a/Dockerfile", "missing": ["package.json"]}
        self.assertEqual(build_context.run(testkit.ctx(inspect={"build_contexts": [bad]}))[0]["severity"], "error")
        self.assertEqual(build_context.run(testkit.ctx(inspect={"build_contexts": [{**bad, "missing": []}]})), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(build_context.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
