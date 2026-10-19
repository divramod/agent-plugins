"""Tests of gate.py: only a strictly higher validation mean is accepted."""

import unittest

import gate


class GateTest(unittest.TestCase):
    def test_gain_accepted(self):
        v = gate.decide(0.75, 0.5)
        self.assertTrue(v["accept"])
        self.assertAlmostEqual(v["margin"], 0.25)
        self.assertIn("accepted", v["reason"])

    def test_tie_rejected(self):
        v = gate.decide(0.5, 0.5)
        self.assertFalse(v["accept"])
        self.assertEqual(v["margin"], 0.0)
        self.assertIn("tie", v["reason"])

    def test_float_noise_is_a_tie(self):
        self.assertFalse(gate.decide(0.1 + 0.2, 0.3)["accept"])
        self.assertFalse(gate.decide(1 / 3 + 1e-12, 1 / 3)["accept"])

    def test_loss_rejected(self):
        v = gate.decide(0.4, 0.5)
        self.assertFalse(v["accept"])
        self.assertLess(v["margin"], 0)
        self.assertIn("fell", v["reason"])

    def test_accepts_judge_split_dicts(self):
        v = gate.decide({"mean": 1.0, "n": 4, "evals": []}, {"mean": 0.5, "n": 4, "evals": []})
        self.assertTrue(v["accept"])
        self.assertEqual((v["candidate"], v["incumbent"]), (1.0, 0.5))

    def test_zero_to_something(self):
        self.assertTrue(gate.decide(0.01, 0.0)["accept"])


if __name__ == "__main__":
    unittest.main()
