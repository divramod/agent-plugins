"""Tests of edits.py: anchors, limits, the size cap, the protected name, the diff (no model call)."""

import subprocess
import tempfile
import unittest
from pathlib import Path

import edits

SKILL = ("---\nname: demo\ndescription: show the open questions\n---\n\n# demo\n\n"
         "Run `python3 q.py`.\nPrint its output unchanged.\n" + "Some filler line of the skill.\n" * 10)


class ApplyTest(unittest.TestCase):
    def test_replace_delete_add(self):
        out = edits.apply(SKILL, [
            {"op": "replace", "anchor": "Run `python3 q.py`.", "text": "Run `python3 q.py --open`."},
            {"op": "delete", "anchor": "Print its output unchanged.\n"},
            {"op": "add", "anchor": "# demo", "text": "Never summarize."}])
        self.assertEqual(out["applied"], 3, out["verdicts"])
        self.assertTrue(out["changed"])
        self.assertIn("Run `python3 q.py --open`.", out["text"])
        self.assertNotIn("Print its output", out["text"])
        self.assertIn("# demo\nNever summarize.\n", out["text"])
        self.assertTrue(all(v["ok"] and v["reason"] is None for v in out["verdicts"]))

    def test_add_mid_line_is_literal(self):
        out = edits.apply(SKILL, [{"op": "add", "anchor": "Run `python3", "text": " -I"}])
        self.assertIn("Run `python3 -I q.py`.", out["text"])

    def test_add_keeps_given_leading_newline(self):
        out = edits.apply(SKILL, [{"op": "add", "anchor": "# demo", "text": "\n\nA rule."}])
        self.assertIn("# demo\n\nA rule.\n", out["text"])

    def test_anchor_missing_or_repeated(self):
        out = edits.apply(SKILL, [{"op": "delete", "anchor": "no such text"},
                                  {"op": "delete", "anchor": "Some filler line"}])
        self.assertEqual(out["applied"], 0)
        self.assertFalse(out["changed"])
        self.assertEqual(out["text"], SKILL)
        self.assertIn("0 times", out["verdicts"][0]["reason"])
        self.assertIn("10 times", out["verdicts"][1]["reason"])

    def test_overlapping_anchor_counts_twice(self):
        self.assertEqual(edits.occurrences("aaa", "aa"), 2)
        out = edits.apply("x aaa y", [{"op": "delete", "anchor": "aa"}])
        self.assertFalse(out["verdicts"][0]["ok"])

    def test_rejected_edit_keeps_later_ones(self):
        out = edits.apply(SKILL, [{"op": "delete", "anchor": "missing"},
                                  {"op": "replace", "anchor": "# demo", "text": "# Demo"}])
        self.assertEqual([v["ok"] for v in out["verdicts"]], [False, True])
        self.assertIn("# Demo", out["text"])

    def test_edits_see_the_evolving_text(self):
        out = edits.apply(SKILL, [{"op": "replace", "anchor": "# demo", "text": "# Demo"},
                                  {"op": "replace", "anchor": "# demo", "text": "# x"}])
        self.assertEqual([v["ok"] for v in out["verdicts"]], [True, False])

    def test_at_most_four_edits(self):
        words = ["Run", "Print", "description: show", "# demo", "unchanged"]
        out = edits.apply(SKILL, [{"op": "replace", "anchor": w, "text": w.upper()} for w in words])
        self.assertEqual(out["applied"], 4)
        self.assertEqual(out["verdicts"][4]["reason"], "over the edit limit (4)")
        self.assertIn("unchanged", out["text"])
        none = edits.apply(SKILL, [{"op": "delete", "anchor": "# demo"}], max_edits=0)
        self.assertEqual((none["applied"], none["text"]), (0, SKILL))

    def test_size_cap(self):
        cap = edits.size_cap(SKILL)
        self.assertEqual(cap, int(len(SKILL) * 1.2))
        grow = cap - len(SKILL)
        ok = edits.apply(SKILL, [{"op": "add", "anchor": "# demo", "text": "\n" + "x" * (grow - 1)}])
        self.assertTrue(ok["verdicts"][0]["ok"], ok["verdicts"])
        self.assertEqual(len(ok["text"]), cap)
        out = edits.apply(SKILL, [{"op": "add", "anchor": "# demo", "text": "\n" + "x" * grow},
                                  {"op": "delete", "anchor": "Print its output unchanged.\n"}])
        self.assertIn("size cap", out["verdicts"][0]["reason"])
        self.assertTrue(out["verdicts"][1]["ok"])
        self.assertLessEqual(len(out["text"]), cap)

    def test_size_cap_counts_against_the_incumbent(self):
        grow = edits.size_cap(SKILL) - len(SKILL)
        half = "\n" + "y" * (grow // 2 - 1)
        out = edits.apply(SKILL, [{"op": "add", "anchor": "# demo", "text": half},
                                  {"op": "add", "anchor": "Run `python3 q.py`.", "text": half},
                                  {"op": "add", "anchor": "unchanged.", "text": half}])
        self.assertEqual([v["ok"] for v in out["verdicts"]], [True, True, False])
        self.assertLessEqual(len(out["text"]), edits.size_cap(SKILL))

    def test_name_is_protected(self):
        cases = [{"op": "replace", "anchor": "name: demo", "text": "name: other"},
                 {"op": "delete", "anchor": "name: demo\n"},
                 {"op": "add", "anchor": "description: show the open questions", "text": "name: two"},
                 {"op": "replace", "anchor": "---\nname", "text": "--\nname"}]
        for edit in cases:
            out = edits.apply(SKILL, [edit])
            self.assertEqual(out["text"], SKILL, edit)
            self.assertIn("name", out["verdicts"][0]["reason"], edit)
        desc = edits.apply(SKILL, [{"op": "replace", "anchor": "show the open", "text": "list the open"}])
        self.assertTrue(desc["verdicts"][0]["ok"])

    def test_malformed_edits(self):
        cases = [("not a dict", "JSON object"), ({"op": "move", "anchor": "x"}, "unknown op"),
                 ({"op": "delete", "anchor": ""}, "non-empty"), ({"op": "add", "anchor": "# demo"}, "needs a text"),
                 ({"op": "replace", "anchor": "# demo", "text": "# demo"}, "changes nothing")]
        for edit, reason in cases:
            out = edits.apply(SKILL, [edit])
            self.assertIn(reason, out["verdicts"][0]["reason"], edit)
            self.assertEqual(out["text"], SKILL)

    def test_parse_edits(self):
        self.assertEqual(edits.parse_edits({"edits": []}), [])
        with self.assertRaises(edits.EditError):
            edits.parse_edits({"op": "add"})
        with self.assertRaises(edits.EditError):
            edits.apply(SKILL, "text")


class DiffTest(unittest.TestCase):
    def test_equal_is_empty(self):
        self.assertEqual(edits.unified_diff(SKILL, SKILL, "SKILL.md"), "")

    def test_diff_applies_with_git(self):
        new = edits.apply(SKILL, [{"op": "replace", "anchor": "# demo", "text": "# Demo"}])["text"] + "end"
        diff = edits.unified_diff(SKILL, new, "SKILL.md")
        self.assertTrue(diff.startswith("--- a/SKILL.md\n+++ b/SKILL.md\n"))
        self.assertIn("\\ No newline at end of file", diff)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "SKILL.md").write_text(SKILL, encoding="utf-8")
            (Path(tmp) / "best.diff").write_text(diff, encoding="utf-8")
            done = subprocess.run(["git", "apply", "best.diff"], cwd=tmp, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual((Path(tmp) / "SKILL.md").read_text(encoding="utf-8"), new)


if __name__ == "__main__":
    unittest.main()
