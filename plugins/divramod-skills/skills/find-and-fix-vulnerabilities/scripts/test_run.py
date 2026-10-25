import sys
import unittest

from run import NOT_FOUND, TIMEOUT, Runner


class RealRunner(unittest.TestCase):
    """The real Runner, on the Python interpreter running the test: nothing else is started."""

    def test_output_and_rc(self):
        rc, out, err = Runner().run([sys.executable, "-c", "import sys; print('o'); print('e', file=sys.stderr); sys.exit(3)"])
        self.assertEqual((rc, out.strip(), err.strip()), (3, "o", "e"))

    def test_missing_program_is_127(self):
        rc, _, err = Runner().run(["definitely-not-a-program-xyz"])
        self.assertEqual(rc, NOT_FOUND)
        self.assertIn("not found", err)

    def test_timeout(self):
        rc, _, err = Runner().run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2)
        self.assertEqual(rc, TIMEOUT)
        self.assertIn("timed out", err)


if __name__ == "__main__":
    unittest.main()
