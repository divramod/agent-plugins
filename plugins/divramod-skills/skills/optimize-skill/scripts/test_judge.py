"""Tests of judge.py: each check op, errors scoring 0 and the split aggregate."""

import unittest

import judge


def result(text="Q1: a\nQ2: b", calls=None, error=None):
    return {"final_text": text, "tool_calls": calls if calls is not None else [], "error": error}


def item(*checks, ident=1):
    return {"id": ident, "prompt": "p", "split": "train", "checks": list(checks)}


class CheckTest(unittest.TestCase):
    def passed(self, check, res):
        return judge.run_check(check, res)[0]

    def test_contains(self):
        self.assertTrue(self.passed({"op": "contains", "value": "Q2"}, result()))
        self.assertFalse(self.passed({"op": "contains", "value": "Q3"}, result()))

    def test_not_contains(self):
        self.assertTrue(self.passed({"op": "not_contains", "value": "Q3"}, result()))
        self.assertFalse(self.passed({"op": "not_contains", "value": "Q1"}, result()))

    def test_regex(self):
        self.assertFalse(self.passed({"op": "regex", "value": r"^Q\d: a$"}, result()))
        self.assertTrue(self.passed({"op": "regex", "value": r"Q\d: b"}, result()))
        self.assertFalse(self.passed({"op": "regex", "value": r"Z\d"}, result()))

    def test_max_chars(self):
        self.assertTrue(self.passed({"op": "max_chars", "value": 11}, result()))
        self.assertFalse(self.passed({"op": "max_chars", "value": 10}, result()))
        self.assertTrue(self.passed({"op": "max_chars", "value": 1}, result(text=None)))

    def test_tool_called(self):
        calls = [{"name": "Bash", "input": {"command": "python3 q.py list"}},
                 {"name": "Skill", "input": {"skill": "demo"}}]
        res = result(calls=calls)
        self.assertTrue(self.passed({"op": "tool_called", "name": "Skill"}, res))
        self.assertTrue(self.passed({"op": "tool_called", "name": "Bash", "input": "q.py list"}, res))
        self.assertTrue(self.passed({"op": "tool_called", "name": "Skill", "input": "demo"}, res))
        self.assertFalse(self.passed({"op": "tool_called", "name": "Bash", "input": "demo"}, res))
        self.assertFalse(self.passed({"op": "tool_called", "name": "Read"}, res))
        self.assertTrue(self.passed({"op": "tool_called", "name": "T", "input": "x"},
                                    result(calls=[{"name": "T", "input": "x y"}])))
        self.assertFalse(self.passed({"op": "tool_called", "name": "Skill"}, result(calls=None)))


class JudgeTest(unittest.TestCase):
    def test_fraction_passed(self):
        j = judge.judge_eval(item({"op": "contains", "value": "Q1"}, {"op": "contains", "value": "Q9"},
                                  {"op": "max_chars", "value": 100}, {"op": "regex", "value": "zzz"}), result())
        self.assertEqual(j["score"], 0.5)
        self.assertEqual([c["passed"] for c in j["checks"]], [True, False, True, False])
        self.assertEqual(j["eval_id"], "1")
        self.assertIsNone(j["error"])

    def test_error_scores_zero(self):
        j = judge.judge_eval(item({"op": "contains", "value": "Q1"}), result(error="timeout"))
        self.assertEqual(j["score"], 0.0)
        self.assertEqual(j["error"], "timeout")
        self.assertFalse(j["checks"][0]["passed"])
        self.assertIn("timeout", j["checks"][0]["detail"])

    def test_missing_result_scores_zero(self):
        j = judge.judge_eval(item({"op": "not_contains", "value": "x"}), None)
        self.assertEqual((j["score"], j["error"]), (0.0, "no result"))

    def test_split_mean_and_detail(self):
        evals = [item({"op": "contains", "value": "Q1"}, ident=1), item({"op": "contains", "value": "Q9"}, ident=2),
                 item({"op": "contains", "value": "Q1"}, ident=3)]
        s = judge.judge_split(evals, {"1": result(), 2: result(), "3": result(error="x")})
        self.assertEqual(s["n"], 3)
        self.assertAlmostEqual(s["mean"], 1 / 3)
        self.assertEqual([e["score"] for e in s["evals"]], [1.0, 0.0, 0.0])

    def test_split_missing_result_and_empty(self):
        s = judge.judge_split([item({"op": "contains", "value": "Q1"})], {})
        self.assertEqual(s["mean"], 0.0)
        self.assertEqual(judge.judge_split([], {}), {"mean": 0.0, "n": 0, "evals": []})


if __name__ == "__main__":
    unittest.main()
