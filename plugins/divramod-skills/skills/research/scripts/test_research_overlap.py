"""research.py new checks earlier research and unfinished plans (plan 0593 step 6; plan 0592 D5): overlap.json beside the
doc, a Log line, the hits printed so the research cites, reuses or revisits them instead of repeating."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import research  # noqa: E402

sys.path.insert(0, str(HERE.parent.parent / "plan" / "scripts"))
from overlap_testkit import EMPTY, HIT, calls, fake_cli  # noqa: E402


class ResearchOverlap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def new(self, answer):
        err = io.StringIO()
        with fake_cli(answer) as cli, contextlib.redirect_stderr(err):
            folder = research.new(self.root, "Plan consistency again", "How do plans stay consistent?", author="t")
            made = calls(cli)
        return folder, err.getvalue(), made

    def test_hits_are_written_logged_and_printed_with_the_research_flag(self):
        folder, err, made = self.new(HIT)
        self.assertEqual(json.loads((folder / "overlap.json").read_text()), HIT)
        self.assertIn("CLI-CONTEXT", (folder / "research.md").read_text())
        self.assertIn("CLI-REPORT", err)
        self.assertIn("--research", made[0])

    def test_an_overlap_resolved_research_logs_a_checked_line(self):
        folder, err, _ = self.new(EMPTY)
        self.assertIn("CLI-CONTEXT-NONE", (folder / "research.md").read_text())
        self.assertIn("CLI-REPORT-NONE", err)

    def test_without_the_cli_the_doc_is_written_and_says_unchecked(self):
        folder, err, _ = self.new(None)
        self.assertTrue((folder / "research.md").is_file())
        self.assertFalse((folder / "overlap.json").exists())
        self.assertIn("overlap: overlap unchecked", err)


if __name__ == "__main__":
    unittest.main()
