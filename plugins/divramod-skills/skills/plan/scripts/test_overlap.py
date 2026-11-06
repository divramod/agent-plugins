# Holds the record `overlap-before-planning`.
"""overlap.py and `plan.py new`: the start path runs `hal2-cli-plans overlap`, writes overlap.json and a Context line,
prints the hits to settle, and never blocks without the CLI (plan 0593 step 6; plan 0592 D4, D16)."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import overlap
import testkit
from overlap_testkit import EMPTY, HIT, calls, fake_cli

PLAN = testkit.HERE / "plan.py"


UNCHECKED = (["overlap unchecked"], "- Overlap: overlap unchecked (hal2-cli-plans overlap missing or failed).",
             "overlap: overlap unchecked")


def forms(found):
    return overlap.lines(found), overlap.context_line(found), overlap.report(found)


class Scan(unittest.TestCase):
    def test_a_hit_is_read_and_its_text_is_the_clis_own(self):
        with fake_cli(HIT) as cli:
            found = overlap.scan(Path("/x/repo"), "Milestone\nhitch", ["a.rs"], research=True)
            (call,) = calls(cli)
        self.assertEqual(call, ["overlap", "--goal", "Milestone hitch", "--json", "--repo", "/x/repo", "--files", "a.rs",
                                "--research"])
        self.assertEqual(overlap.hits(found), 2)
        self.assertEqual(forms(found), (["CLI-LINE-1", "CLI-LINE-2"], "- CLI-CONTEXT", "CLI-REPORT"))

    def test_an_empty_answer_has_no_hits_and_the_clis_text(self):
        with fake_cli(EMPTY):
            found = overlap.scan(Path("/x"), "g")
        self.assertEqual(overlap.hits(found), 0)
        self.assertEqual(forms(found), ([], "- CLI-CONTEXT-NONE", "CLI-REPORT-NONE"))

    def test_a_missing_or_older_cli_is_unchecked_and_never_raises(self):
        with fake_cli(None):
            self.assertIsNone(overlap.scan(Path("/x"), "g"))
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            self.assertIsNone(overlap.scan(Path("/x"), "g"))
        self.assertEqual(forms(None), UNCHECKED)

    def test_an_answer_without_a_well_typed_text_is_unchecked(self):
        """An older installed CLI (no `text`) or a broken one: unchecked, never a Python rendering (D5, D6)."""
        bad = [{k: v for k, v in HIT.items() if k != "text"},
               {**HIT, "text": "CLI-REPORT"},
               {**HIT, "text": {**HIT["text"], "lines": "CLI-LINE-1"}},
               {**HIT, "text": {**HIT["text"], "lines": ["CLI-LINE-1", 2]}},
               {**HIT, "text": {**HIT["text"], "context": None}},
               {**HIT, "text": {"lines": [], "context": "- CLI-CONTEXT"}}]
        for answer in bad:
            with self.subTest(answer=answer.get("text")), fake_cli(answer):
                found = overlap.scan(Path("/x"), "g")
                self.assertIsNone(found)
                self.assertEqual(forms(found), UNCHECKED)

    def test_a_failing_or_garbage_cli_is_unchecked(self):
        for answer, code in ((HIT, 1), ("CLI-LINE-1 not json {", 0), ("[1, 2]", 0)):
            with self.subTest(answer=answer, code=code), fake_cli(answer, code):
                self.assertIsNone(overlap.scan(Path("/x"), "g"))

    def test_off_skips_the_scan(self):
        with fake_cli(HIT) as cli, mock.patch.dict(os.environ, {"HAL2_OVERLAP": "off"}):
            self.assertIsNone(overlap.scan(Path("/x"), "g"))
            self.assertEqual(calls(cli), [])


class NoCopy(unittest.TestCase):
    def test_the_module_renders_no_hit_field(self):
        """D6: the CLI owns the text; overlap.py keeps no copy of its format."""
        source = (testkit.HERE / "overlap.py").read_text()
        for name in ("why", "slug", "score", "title"):
            self.assertNotIn(f"get('{name}'", source)
        for name in ("reason", "reasons", "KINDS"):
            self.assertFalse(hasattr(overlap, name), name)


class Contract(unittest.TestCase):
    def test_the_sample_follows_the_contract(self):
        """HIT has the keys of the CLI's contract fixture (record cross-unit-formats-have-a-schema), which the CLI's
        overlap test writes and compares."""
        parts = ("code", "rust", "apps", "hal2-cli-plans", "tests", "fixtures", "expected", "overlap.json")
        fixture = next((p / Path(*parts) for p in testkit.HERE.parents if (p / Path(*parts)).is_file()), None)
        if fixture is None:
            self.skipTest("hal2's contract fixture is not there (an installed plugin)")
        contract = json.loads(fixture.read_text())
        self.assertEqual(contract["schema"], HIT["schema"])
        self.assertEqual(set(HIT), set(contract))
        self.assertEqual(set(HIT["query"]), set(contract["query"]))
        self.assertEqual(set(HIT["scanned"]), set(contract["scanned"]))
        for join in ("plans", "research"):
            self.assertEqual(set(HIT[join][0]), set(contract[join][0]), join)
            self.assertEqual(set(HIT[join][0]["why"][0]), set(contract[join][0]["why"][0]), join)


class PlanNew(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        testkit.init_repo(self.root, "main")
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t", "commit",
                        "--allow-empty", "-qm", "init"], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def new(self, *args):
        return testkit.run(PLAN, ["--root", self.root, "new", "Milestone hitch again", "--goal", "hitch at milestones",
                                  *args], env={**os.environ, "HAL2_OVERLAP": "on"},
                           cwd=self.root)

    def test_hits_are_written_beside_the_plan_and_printed_to_settle(self):
        with fake_cli(HIT) as cli:
            done = self.new()
            self.assertEqual(len([c for c in calls(cli) if c[0] == "overlap"]), 1)
        self.assertEqual(done.returncode, 0, done.stderr)
        folder = next((self.root / "plans").glob("0*-*"))
        self.assertEqual(json.loads((folder / "overlap.json").read_text()), HIT)
        text = (folder / "plan.md").read_text()
        self.assertIn("\n- CLI-CONTEXT\n", text)
        self.assertIn("CLI-REPORT", done.stderr)
        self.assertEqual(json.loads(done.stdout)["overlap"], ["CLI-LINE-1", "CLI-LINE-2"])

    def test_an_overlap_resolved_plan_has_a_checked_line_and_no_hits_to_settle(self):
        with fake_cli(EMPTY):
            done = self.new()
        folder = next((self.root / "plans").glob("0*-*"))
        self.assertIn("- CLI-CONTEXT-NONE", (folder / "plan.md").read_text())
        self.assertIn("CLI-REPORT-NONE", done.stderr)
        self.assertNotIn("settle", done.stderr)

    def test_without_the_cli_the_plan_is_written_and_says_unchecked(self):
        with fake_cli(None):
            done = self.new()
        self.assertEqual(done.returncode, 0, done.stderr)
        folder = next((self.root / "plans").glob("0*-*"))
        self.assertFalse((folder / "overlap.json").exists())
        self.assertIn("- Overlap: overlap unchecked", (folder / "plan.md").read_text())
        self.assertIn("overlap: overlap unchecked", done.stderr)


if __name__ == "__main__":
    unittest.main()
