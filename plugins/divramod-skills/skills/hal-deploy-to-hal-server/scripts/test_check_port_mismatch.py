import unittest

import inspect_repo
import testkit
from checks import port_mismatch


def ctx(port, dockerfile="FROM node\nEXPOSE 3000\n"):
    repo = testkit.repo(testkit.scratch(), dockerfile=dockerfile)
    return {"site": "accounter", "container": {"port": port}, "inspect": inspect_repo.inspect(repo)}


class PortMismatchTest(unittest.TestCase):
    def test_other_port_is_a_warning(self):
        found = port_mismatch.run(ctx(8080))
        self.assertEqual([f["check"] for f in found], ["port-mismatch"])
        self.assertIn("3000", found[0]["detail"])

    def test_same_port_and_no_expose_pass(self):
        self.assertEqual(port_mismatch.run(ctx(3000)), [])
        self.assertEqual(port_mismatch.run(ctx(8080, dockerfile="FROM node\n")), [])


if __name__ == "__main__":
    unittest.main()
