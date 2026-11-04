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


class Scan(unittest.TestCase):
    def test_a_hit_is_read_and_listed_plans_first(self):
        with fake_cli(HIT) as cli:
            found = overlap.scan(Path("/x/repo"), "Milestone\nhitch", ["a.rs"], research=True)
            (call,) = calls(cli)
        self.assertEqual(call, ["overlap", "--goal", "Milestone hitch", "--json", "--repo", "/x/repo", "--files", "a.rs",
                                "--research"])
        self.assertEqual(overlap.hits(found), 2)
        lines = overlap.lines(found)
        self.assertTrue(lines[0].startswith("plan 0571-milestone-hitch (open, field 12"))
        self.assertTrue(lines[1].startswith("research 0131-plan-consistency"))

    def test_an_empty_answer_has_no_hits(self):
        with fake_cli(EMPTY):
            found = overlap.scan(Path("/x"), "g")
        self.assertEqual((overlap.hits(found), overlap.lines(found)), (0, []))
        self.assertEqual(overlap.report(found), "overlap: none")

    def test_a_missing_or_older_cli_is_unchecked_and_never_raises(self):
        with fake_cli(None):
            self.assertIsNone(overlap.scan(Path("/x"), "g"))
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            self.assertIsNone(overlap.scan(Path("/x"), "g"))
        self.assertEqual(overlap.lines(None), ["overlap unchecked"])

    def test_off_skips_the_scan(self):
        with fake_cli(HIT) as cli, mock.patch.dict(os.environ, {"HAL2_OVERLAP": "off"}):
            self.assertIsNone(overlap.scan(Path("/x"), "g"))
            self.assertEqual(calls(cli), [])


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
        self.assertIn("- Overlap: 0571-milestone-hitch, 0131-plan-consistency (see [overlap.json](overlap.json))", text)
        self.assertIn("overlap: plan 0571-milestone-hitch", done.stderr)
        self.assertIn("settle each hit before writing", done.stderr)
        self.assertEqual(len(json.loads(done.stdout)["overlap"]), 2)

    def test_an_overlap_resolved_plan_has_a_checked_line_and_no_hits_to_settle(self):
        with fake_cli(EMPTY):
            done = self.new()
        folder = next((self.root / "plans").glob("0*-*"))
        self.assertIn("- Overlap: checked", (folder / "plan.md").read_text())
        self.assertIn("overlap: none", done.stderr)
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
