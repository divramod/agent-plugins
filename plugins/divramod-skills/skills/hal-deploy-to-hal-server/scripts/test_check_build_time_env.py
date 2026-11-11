import unittest

import testkit
from checks import build_time_env


class BuildTimeEnvTest(unittest.TestCase):
    def test_needed_names_warn(self):
        found = build_time_env.run(testkit.ctx(inspect={"env_names": ["NEXT_PUBLIC_X", "DATABASE_URL"]}))
        self.assertEqual(found[0]["severity"], "warn")
        self.assertNotIn("DATABASE_URL", found[0]["detail"])

    def test_declaring_one_is_an_error(self):
        found = build_time_env.run(testkit.ctx(container={"env": {"VITE_API": "x"}}))
        self.assertEqual(found[0]["severity"], "error")

    def test_undeclared_env_leaves_them_to_this_check(self):
        from checks import undeclared_env
        self.assertEqual(undeclared_env.run(testkit.ctx(inspect={"env_names": ["PUBLIC_X"]})), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(build_time_env.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
