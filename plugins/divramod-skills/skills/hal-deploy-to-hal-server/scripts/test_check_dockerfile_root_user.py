import unittest

import testkit
from checks import dockerfile_root_user


class DockerfileRootUserTest(unittest.TestCase):
    def docker(self, user):
        return {"docker": {"Dockerfile": {"ports": [], "user": user, "copies_node_modules": False}}}

    def test_no_user_or_root(self):
        self.assertEqual(len(dockerfile_root_user.run(testkit.ctx(inspect=self.docker(None)))), 1)
        self.assertEqual(len(dockerfile_root_user.run(testkit.ctx(inspect=self.docker("root")))), 1)

    def test_a_named_user(self):
        self.assertEqual(dockerfile_root_user.run(testkit.ctx(inspect=self.docker("node"))), [])

    def test_without_a_repository_it_finds_nothing(self):
        self.assertEqual(dockerfile_root_user.run({"site": "demo", "container": {}, "inspect": None}), [])


if __name__ == "__main__":
    unittest.main()
