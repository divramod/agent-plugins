import unittest

import inspect_repo
import testkit
from checks import undeclared_env


def ctx(**container):
    repo = testkit.repo(testkit.scratch())
    return {"site": "accounter", "container": container, "inspect": inspect_repo.inspect(repo)}


class UndeclaredEnvTest(unittest.TestCase):
    def test_names_not_declared_are_listed(self):
        found = undeclared_env.run(ctx(env={"NODE_ENV": "production"}, secrets=["DATABASE_URL"]))
        self.assertEqual(len(found), 1)
        self.assertIn("STORAGE_DRIVER", found[0]["detail"])
        self.assertNotIn("DATABASE_URL", found[0]["detail"])

    def test_all_declared_passes(self):
        self.assertEqual(undeclared_env.run(ctx(env={"NODE_ENV": "x", "STORAGE_DRIVER": "s3"},
                                                secrets=["DATABASE_URL"])), [])


if __name__ == "__main__":
    unittest.main()
