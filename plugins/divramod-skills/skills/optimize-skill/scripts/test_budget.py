"""Tests of budget.py: the ledger, its reload and the hard caps."""

import json
import os
import tempfile
import unittest
from pathlib import Path

import budget
import fake_claude
import rollout

USAGE = {"input": 10, "output": 90, "cache_read": 800, "cache_creation": 100, "total": 1000}


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "run" / "ledger.jsonl"

    def lines(self):
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def test_defaults_and_caps_line(self):
        ledger = budget.Ledger(self.path)
        self.assertEqual((ledger.max_tokens, ledger.max_rollouts), (5_000_000, 80))
        self.assertEqual(self.lines()[0]["kind"], "caps")
        self.assertEqual(ledger.remaining(), {"tokens": 5_000_000, "rollouts": 80})

    def test_regression_zero_caps_are_refused(self):  # review 7: 0 used to become the default silently
        for caps in ({"max_tokens": 0}, {"max_rollouts": 0}, {"max_tokens": -5}):
            with self.subTest(caps=caps), self.assertRaisesRegex(ValueError, "positive"):
                budget.Ledger(self.path, **caps)
        self.assertFalse(self.path.exists())  # refused before the caps line
        ledger = budget.Ledger(self.path, max_tokens=1, max_rollouts=1)
        self.assertEqual((ledger.max_tokens, ledger.max_rollouts), (1, 1))

    def test_floored(self):  # review 2: a cut-off call is charged at least its estimate
        self.assertEqual(budget.floored(USAGE, 60_000)["total"], 60_000)
        self.assertEqual(budget.floored(USAGE, 10)["total"], 1000)
        self.assertEqual(budget.floored({}, 5)["total"], 5)
        ledger = budget.Ledger(self.path)
        ledger.charge(budget.floored(USAGE, 60_000), floored=True)
        self.assertEqual((ledger.spent, self.lines()[-1]["floored"], self.lines()[-1]["input"]), (60_000, True, 10))

    def test_charge_exact_usage(self):
        ledger = budget.Ledger(self.path, max_tokens=5000)
        entry = ledger.charge(USAGE, cost_usd=0.003, eval_id="e1", candidate=0)
        self.assertEqual(entry["tokens"], 1000)
        self.assertEqual((entry["input"], entry["cache_read"], entry["eval_id"]), (10, 800, "e1"))
        ledger.charge({"input": 1, "output": 2, "cache_read": 3, "cache_creation": 4}, kind="reflect")
        self.assertEqual(ledger.spent, 1010)
        self.assertEqual(ledger.rollouts, 1)  # a reflection is no rollout
        self.assertEqual(ledger.remaining(), {"tokens": 3990, "rollouts": 79})
        self.assertEqual([line["kind"] for line in self.lines()], ["caps", "rollout", "reflect"])
        with self.assertRaises(ValueError):
            ledger.charge(USAGE, kind="guess")

    def test_token_cap_stops(self):
        ledger = budget.Ledger(self.path, max_tokens=2500)
        ledger.check(1000)
        ledger.charge(USAGE)
        ledger.check(1000)
        ledger.charge(USAGE)
        self.assertIsNotNone(ledger.would_exceed(1000))  # 2000 + 1000 > 2500
        self.assertIsNone(ledger.would_exceed(500))
        ledger.charge(USAGE)  # a call that went over is charged in full
        self.assertEqual(ledger.spent, 3000)
        with self.assertRaises(budget.BudgetExceeded) as caught:
            ledger.check(0, kind="reflect")
        self.assertIn("token cap reached", str(caught.exception))
        self.assertEqual(ledger.remaining()["tokens"], 0)

    def test_rollout_cap_stops_rollouts_only(self):
        ledger = budget.Ledger(self.path, max_rollouts=2)
        ledger.charge(USAGE)
        ledger.charge(USAGE)
        with self.assertRaises(budget.BudgetExceeded):
            ledger.check(kind="rollout")
        ledger.check(kind="edit")

    def test_reload_keeps_spent_and_caps(self):
        ledger = budget.Ledger(self.path, max_tokens=4000, max_rollouts=3)
        ledger.charge(USAGE, cost_usd=0.5)
        ledger.charge(USAGE, kind="edit", cost_usd=0.25)
        again = budget.Ledger(self.path)
        self.assertEqual((again.max_tokens, again.max_rollouts), (4000, 3))
        self.assertEqual((again.spent, again.rollouts, again.cost_usd), (2000, 1, 0.75))
        self.assertEqual(len(self.lines()), 3)  # no second caps line for the same caps
        raised = budget.Ledger(self.path, max_tokens=9000)
        self.assertEqual(raised.max_tokens, 9000)
        self.assertEqual(budget.Ledger(self.path).max_tokens, 9000)  # the newest caps line wins
        self.assertEqual(raised.summary()["spent"], 2000)

    def test_junk_lines_ignored(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('not json\n{"kind": "rollout", "tokens": 7}\n[1]\n', encoding="utf-8")
        ledger = budget.Ledger(self.path)
        self.assertEqual((ledger.spent, ledger.rollouts), (7, 1))

    def test_loop_on_fake_claude_stops_at_cap(self):
        """The loop shape optimize.py will use: check, rollout, charge; the cap ends it before a call."""
        bin_dir = self.tmp / "bin"
        claude = fake_claude.install(bin_dir)
        ledger = budget.Ledger(self.path, max_tokens=200_000)  # one fake rollout is 84,966 tokens
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.tmp)}
        ran = 0
        with self.assertRaises(budget.BudgetExceeded):
            for n in range(10):
                ledger.check(estimate=60_000)
                result = rollout.run("demo", "# demo\n", {"id": str(n), "prompt": "p"}, workspace=self.tmp / "ws",
                                     claude=claude, env=env)
                ledger.charge(result["usage"], cost_usd=result["cost_usd"], eval_id=result["eval_id"])
                ran += 1
        self.assertEqual(ran, 2)  # 2 x 84,966 = 169,932; + 60,000 estimated > 200,000
        self.assertEqual(len(fake_claude.calls(bin_dir)), 2)
        self.assertLessEqual(ledger.spent, 200_000)


if __name__ == "__main__":
    unittest.main()
