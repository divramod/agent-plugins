import unittest

import inspect_repo
import testkit
from checks import dockerfile_missing


def ctx(repo):
    return {"site": "accounter", "container": {"port": 3000}, "inspect": inspect_repo.inspect(repo) if repo else None}


class DockerfileMissingTest(unittest.TestCase):
    def test_no_dockerfile_is_an_error(self):
        found = dockerfile_missing.run(ctx(testkit.repo(testkit.scratch(), dockerfile=None)))
        self.assertEqual([(f["check"], f["severity"]) for f in found], [("dockerfile-missing", "error")])

    def test_a_dockerfile_passes(self):
        self.assertEqual(dockerfile_missing.run(ctx(testkit.repo(testkit.scratch()))), [])

    def test_without_a_repository_nothing(self):
        self.assertEqual(dockerfile_missing.run(ctx(None)), [])


if __name__ == "__main__":
    unittest.main()
