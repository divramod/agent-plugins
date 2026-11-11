import unittest

import testkit
from checks import vercel_runtime


class VercelRuntimeTest(unittest.TestCase):
    def test_the_preset_and_the_env_reader(self):
        found = vercel_runtime.run(testkit.ctx(inspect={"vercel": {"deps": ["@vercel/react-router"], "env_readers": ["a.ts"]}}))
        self.assertEqual(len(found), 2)

    def test_a_declared_vercel_env_or_a_plain_app(self):
        vercel = {"deps": [], "env_readers": ["a.ts"]}
        declared = testkit.ctx(container={"env": {"VERCEL_ENV": "production"}}, inspect={"vercel": vercel})
        self.assertEqual(vercel_runtime.run(declared), [])
        self.assertEqual(vercel_runtime.run(testkit.ctx()), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(vercel_runtime.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
