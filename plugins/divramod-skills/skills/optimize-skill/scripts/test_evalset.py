"""Tests of evalset.py: loading, validation (all problems at once), the splits and the skeleton."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import evalset


def good():
    return {"skill_name": "demo", "evals": [
        {"id": 1, "prompt": "p1", "expected_output": "o", "files": [], "expectations": ["e"], "split": "train",
         "checks": [{"op": "contains", "value": "Q1"}, {"op": "max_chars", "value": 500}]},
        {"id": 2, "prompt": "p2", "split": "val",
         "checks": [{"op": "tool_called", "name": "Skill", "input": "demo"}, {"op": "regex", "value": r"Q\d+"},
                    {"op": "not_contains", "value": "error"}]},
        {"id": 3, "prompt": "p3", "split": "train", "checks": [{"op": "contains", "value": "x"}]},
    ]}


class ValidateTest(unittest.TestCase):
    def test_valid_set(self):
        self.assertEqual(evalset.validate(good()), [])

    def test_splits(self):
        s = evalset.EvalSet(good())
        self.assertEqual([e["id"] for e in s.train()], [1, 3])
        self.assertEqual([e["id"] for e in s.val()], [2])
        self.assertEqual(s.get("2")["prompt"], "p2")
        self.assertEqual(s.skill_name, "demo")
        with self.assertRaises(KeyError):
            s.get(99)

    def test_missing_checks(self):
        for bad in (None, []):
            data = good()
            if bad is None:
                del data["evals"][0]["checks"]
            else:
                data["evals"][0]["checks"] = bad
            errors = evalset.validate(data)
            self.assertTrue(any("eval 1" in e and "needs checks" in e for e in errors), errors)

    def test_unknown_op_and_bad_values(self):
        data = good()
        data["evals"][0]["checks"] = [{"op": "equals", "value": "x"}, {"op": "max_chars", "value": 0},
                                      {"op": "max_chars", "value": True}, {"op": "contains"},
                                      {"op": "regex", "value": "("}, {"op": "tool_called"},
                                      {"op": "tool_called", "name": "Bash", "input": 3}, "oops"]
        errors = evalset.validate(data)
        self.assertEqual(len(errors), 8, errors)
        self.assertIn("unknown op 'equals'", errors[0])
        self.assertTrue(any("does not compile" in e for e in errors))

    def test_not_contains_accepts_an_empty_value(self):
        data = good()
        data["evals"][0]["checks"] = [{"op": "not_contains", "value": ""}]
        self.assertEqual(evalset.validate(data), [])

    def test_missing_split_is_refused(self):
        for keep in ("train", "val"):
            data = good()
            for e in data["evals"]:
                e["split"] = keep
            errors = evalset.validate(data)
            other = "val" if keep == "train" else "train"
            self.assertIn(f"the set has no {other} eval", errors)

    def test_bad_split_value(self):
        data = good()
        data["evals"][0]["split"] = "test"
        self.assertTrue(any("split must be one of" in e for e in evalset.validate(data)))

    def test_duplicate_ids(self):
        data = good()
        data["evals"][2]["id"] = "1"
        self.assertTrue(any("eval 1: duplicate id" in e for e in evalset.validate(data)))

    def test_all_problems_at_once(self):
        data = copy.deepcopy(good())
        data["evals"][0]["prompt"] = ""
        data["evals"][1]["checks"] = []
        data["evals"][2]["id"] = 1
        with self.assertRaises(evalset.EvalSetError) as ctx:
            evalset.EvalSet(data)
        self.assertGreaterEqual(len(ctx.exception.errors), 3)

    def test_shape_errors(self):
        self.assertEqual(evalset.validate([]), ["the file must hold an object"])
        self.assertEqual(evalset.validate({"skill_name": "a"}), ["needs evals (a non-empty list)"])
        self.assertIn("an eval must be an object", evalset.validate({"skill_name": "a", "evals": ["x"]})[0])
        data = good()
        data["evals"][0]["files"] = "a.txt"
        self.assertTrue(any("files must be a list" in e for e in evalset.validate(data)))
        data["evals"][0]["files"] = ["evals/files/q.md", {"dest": "Q.md", "text": "# q"}, {"src": "/a", "dest": "b"}]
        self.assertEqual([e for e in evalset.validate(data) if "files" in e], [])
        for bad in ({"text": "no dest"}, {"dest": "x"}, {"dest": "x", "text": 1}, 3, ""):
            data["evals"][0]["files"] = [bad]
            self.assertTrue(any("files must be a list" in e for e in evalset.validate(data)), bad)
        del data["skill_name"]
        self.assertIn("needs a skill_name", evalset.validate(data))


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.skill = Path(tempfile.mkdtemp()) / "demo"
        (self.skill / "evals").mkdir(parents=True)

    def test_load_folder_and_file(self):
        file = self.skill / "evals" / "evals.json"
        file.write_text(json.dumps(good()), encoding="utf-8")
        self.assertEqual(len(evalset.load(self.skill).evals), 3)
        self.assertEqual(len(evalset.load(file).val()), 1)

    def test_missing_and_broken_file(self):
        with self.assertRaises(evalset.EvalSetError) as ctx:
            evalset.load(self.skill)
        self.assertIn("does not exist", ctx.exception.errors[0])
        (self.skill / "evals" / "evals.json").write_text("{nope", encoding="utf-8")
        with self.assertRaises(evalset.EvalSetError) as ctx:
            evalset.load(self.skill)
        self.assertIn("cannot be read as JSON", ctx.exception.errors[0])

    def test_load_refuses_invalid_set(self):
        data = good()
        data["evals"][0]["checks"] = []
        (self.skill / "evals" / "evals.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(evalset.EvalSetError):
            evalset.load(self.skill)


class SkeletonTest(unittest.TestCase):
    def test_skeleton_is_valid_and_marked(self):
        data = evalset.skeleton("demo")
        self.assertEqual(data["skill_name"], "demo")
        self.assertEqual(evalset.validate(data), [])
        self.assertTrue(evalset.is_skeleton(data))
        self.assertFalse(evalset.is_skeleton(good()))
        s = evalset.EvalSet(data)
        self.assertEqual((len(s.train()), len(s.val())), (1, 1))


if __name__ == "__main__":
    unittest.main()
