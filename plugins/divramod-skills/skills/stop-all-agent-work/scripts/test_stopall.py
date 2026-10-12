import json
import os
import tempfile
import unittest
from pathlib import Path

import stopall


class StopAllTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["STOP_ALL_AGENT_WORK_ROOT"] = self.tmp.name

    def tearDown(self):
        del os.environ["STOP_ALL_AGENT_WORK_ROOT"]
        self.tmp.cleanup()

    def state(self):
        return json.loads((Path(self.tmp.name) / "state.json").read_text())

    def test_save_status_finish(self):
        self.assertEqual(stopall.main(["status"]), 1)
        self.assertEqual(stopall.main(["save", "--stopped", "a", "b", "--keep", "k", "--note", "bench"]), 0)
        self.assertEqual(self.state()["stopped"], ["a", "b"])
        self.assertEqual(self.state()["keep"], ["k"])
        self.assertEqual(stopall.main(["status"]), 0)
        self.assertEqual(stopall.main(["finish"]), 0)
        self.assertEqual(stopall.main(["status"]), 1)
        hist = list((Path(self.tmp.name) / "history").glob("*.json"))
        self.assertEqual(len(hist), 1)
        self.assertIn("continued_at", json.loads(hist[0].read_text()))

    def test_second_stop_adds_names(self):
        stopall.main(["save", "--stopped", "a", "--keep", "k"])
        stopall.main(["save", "--stopped", "a", "k", "c"])
        s = self.state()
        self.assertEqual(s["stopped"], ["a", "k", "c"])
        self.assertEqual(s["keep"], [])
        self.assertEqual(len(s["again"]), 1)


if __name__ == "__main__":
    unittest.main()
