"""A failed run's follow-up carries the run's exit and output (run_failed.py; the tollman, 2026-11-04): the woken
session reads why instead of running the command again."""

import unittest

from run_failed import TAIL, failed


class Failed(unittest.TestCase):
    def test_the_wake_line_ends_with_the_exit_and_the_outputs_tail(self):
        f = failed({"do": "wake", "text": "restart failed"}, 1, "line one\nthe queue refused: held by pid 1820\n")
        self.assertEqual(f["text"], "restart failed [exit 1: line one the queue refused: held by pid 1820]")
        self.assertEqual(f["do"], "wake")

    def test_a_long_output_keeps_its_tail_and_the_evidence_the_last_2000(self):
        out = "x" * 5000 + "END"
        f = failed({"text": "t"}, 3, out)
        self.assertTrue(f["text"].endswith("END]"))
        self.assertLessEqual(len(f["text"]), TAIL + 20)
        self.assertEqual(f["output"], out[-2000:])

    def test_no_output_says_so_and_the_action_itself_is_not_changed(self):
        follow = {"text": "t"}
        self.assertEqual(failed(follow, 1, "")["text"], "t [exit 1: no output]")
        self.assertEqual(follow, {"text": "t"})


if __name__ == "__main__":
    unittest.main()
