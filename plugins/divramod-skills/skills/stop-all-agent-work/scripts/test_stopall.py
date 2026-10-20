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


    def test_no_abort_text_for_a_landing(self):
        # gap 13 (plan 0397 D7): the stop pauses a landing in place and the continue resumes it, never "aborted"
        skills = Path(__file__).resolve().parents[2]
        texts = [(skills / n / "SKILL.md").read_text() for n in ("stop-all-agent-work", "continue-all-agent-work")]
        for text in texts:
            self.assertNotIn("aborts the landing", text)
            self.assertNotIn("landing was aborted", text)
            self.assertNotIn("start a NEW", text)
            self.assertNotIn("start a new /mtm", text)
        self.assertIn("never abort it", texts[0])
        self.assertIn("adopts", texts[1])


if __name__ == "__main__":
    unittest.main()
