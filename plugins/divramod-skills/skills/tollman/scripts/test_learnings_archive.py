"""Hal2 plan 0490 step 14 (D15): `learnings.py archive <n>... --why <commit|plan>` moves entries into `## Archive`;
`rules`, `untaken` and the verdicts review skip them, a new entry goes before the section and numbers are never reused.
Hermetic: a tmp role folder, a fake metrics measure."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import learnings
import learnings_archive
import verdicts

TODAY = "2026-10-30"


class Archive(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "roles" / "tollman"
        self.dir.mkdir(parents=True)
        for i in (1, 2, 3):
            learnings.add(self.dir, f"case {i}", "cause", f"rule {i}", "y", at="2026-10-14 09:30Z", metric="restarts")

    def archive(self, *numbers, why="abc1234"):
        return learnings_archive.archive(self.dir, set(numbers), why, today=TODAY)

    def text(self):
        return (self.dir / "learnings.md").read_text()

    def test_archived_entries_leave_rules_untaken_and_the_review(self):
        self.assertEqual(self.archive(1, 3), [1, 3])
        self.assertEqual([e.n for e in learnings.read(self.dir)], [2])
        self.assertEqual([e.n for e in learnings.untaken(self.dir)], [2])
        self.assertEqual([l.split()[0] for l in learnings.rules_text(self.dir).splitlines()], ["L2"])
        found = verdicts.review(self.dir, TODAY, ci=lambda: [])  # no train lines in the tmp folder
        self.assertEqual([a["n"] for a in found], [2])
        self.assertNotIn("L1 ", (self.dir / "stats.md").read_text())

    def test_the_entries_keep_their_text_and_say_why_under_the_archive_heading(self):
        self.archive(1, why="plan 0490 row 11")
        head, tail = self.text().split("\n## Archive\n")
        self.assertNotIn("L1 ·", head)
        self.assertIn("## L1 · 2026-10-14 09:30Z · case-1", tail)
        self.assertIn("**Rule:** rule 1\n", tail)
        self.assertIn("**Archived:** 2026-10-30 plan 0490 row 11\n", tail)
        self.assertEqual(self.archive(3), [3])  # a second archive appends to the one section
        self.assertEqual(self.text().count("## Archive"), 1)

    def test_an_unknown_or_archived_number_moves_nothing_and_a_why_is_required(self):
        self.archive(1)
        self.assertEqual(self.archive(1, 9), [])
        with self.assertRaises(ValueError):
            learnings_archive.archive(self.dir, {2}, "  ")
        self.assertEqual([e.n for e in learnings.read(self.dir)], [2, 3])

    def test_a_new_entry_goes_before_the_archive_and_the_number_is_not_reused(self):
        self.archive(3)
        e = learnings.add(self.dir, "case 4", "cause", "rule 4", "n", at="2026-10-30 10:00Z")
        self.assertEqual(e.n, 4)
        self.assertEqual([x.n for x in learnings.read(self.dir)], [1, 2, 4])
        self.assertLess(self.text().index("## L4 "), self.text().index("## Archive"))

    def test_mark_taken_and_set_fields_ignore_an_archived_entry(self):
        self.archive(1)
        self.assertEqual(learnings.mark_taken(self.dir, {1, 2}, "p", today=TODAY), [2])

    def test_the_cli_archives_and_exits_1_when_nothing_moved(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(learnings.main(["--dir", str(self.dir), "archive", "1", "2", "--why", "abc"]), 0)
            self.assertEqual(learnings.main(["--dir", str(self.dir), "archive", "7", "--why", "abc"]), 1)
        self.assertEqual(out.getvalue().splitlines(), ["archived: L1, L2", "archived: none"])
