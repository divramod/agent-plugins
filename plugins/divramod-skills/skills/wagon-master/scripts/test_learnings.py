"""Hal2 plan 0313 step 4 (D8): the learnings file writer and reader (learnings.py): the entry shape, numbering,
`untaken`, `mark-taken`, extra `**Key:**` fields kept (step 7's Start and Metric), the hand-written legacy shape the
wagon master started on 2026-10-14 (copied into the fixture, the live file is never read), and the CLI."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import learnings

LEGACY = """# wagon-master learnings (hal2)

Read at the start of every `/wagon-master act` and applied.

## 2026-10-14 · The carrier's remote branch keeps a dead train

- **What**: train 07 (09:2x) and later trains failed at `git push origin HEAD:refs/heads/wagon-master-hal2`:
  non-fast-forward. Fixed by hand three times.
- **Cause**: after a split or breakup the engine resets the carrier locally.
- **Rule**: right after every split or breakup, check that origin equals the local carrier.
- **Code**: yes. engine.py should push the reset with a lease (engine foreman, wt 17).

## 2026-10-14 · Cars rode without proof and broke trains

- **What**: 06 (`python-lint`) and 07 (`lua-test`) each broke a train.
- **Rule** (the user's, via the farmer, 2026-10-14): a car rides only with proof that its light gate jobs are green.
- **Code**: yes. The train should run the light jobs.

## 2026-10-14 · A big diff overflows the gate's jq call

- **What**: train 06+05+10 went red in `changes`.
- **Rule**: a gate fault no car caused goes to the farmer.
- **Code**: fixed by 09's b62949cb6 (carried by 05 and 09).

## 2026-10-14 · Other surprises

- The orphan scan counts a field's nested hand worktrees as fields without a session. Code: yes (wt 17).
"""


class Learnings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "roles" / "wagon-master"
        self.dir.mkdir(parents=True)

    def add(self, case="a train broke", n="y", **kw):
        return learnings.add(self.dir, case, "the cause", "the rule", n, at="2026-10-14 09:30Z", **kw)

    def test_add_writes_the_entry_shape(self):
        e = self.add("Push refused: not a fast-forward", extra=[("Start", "2026-10-14")])
        text = (self.dir / "learnings.md").read_text()
        self.assertTrue(text.startswith("---\ntype: Ledger\nschema: 1\nrole: wagon-master\n"))
        self.assertIn("\n# wagon-master learnings\n", text)
        self.assertIn("## L1 · 2026-10-14 09:30Z · push-refused-not-a-fast-forward\n\n**Case:** Push refused", text)
        order = [l.split(":")[0] for l in text.splitlines() if l.startswith("**")]
        self.assertEqual(order, ["**Case", "**Cause", "**Rule", "**Code change", "**Start", "**Taken"])
        self.assertIn("**Taken:** -", text)
        self.assertEqual((e.n, e.code, e.taken, e.fields["start"]), (1, "y", "", "2026-10-14"))

    def test_numbers_go_on_and_entries_roundtrip(self):
        self.add("one")
        self.add("two", n="n", slug="second case")
        got = learnings.read(self.dir)
        self.assertEqual([(e.n, e.slug, e.code) for e in got], [(1, "one", "y"), (2, "second-case", "n")])
        self.assertEqual(got[1].rule, "the rule")

    def test_field_text_stays_one_line(self):
        learnings.add(self.dir, "a\n## L9 · x · y\n**Rule:** evil", "c", "r", at="2026-10-14 09:30Z")
        self.assertEqual([e.n for e in learnings.read(self.dir)], [1])

    def test_untaken_and_mark_taken(self):
        for c in ("one", "two", "three"):
            self.add(c, n="n" if c == "two" else "y")
        self.assertEqual(learnings.mark_taken(self.dir, {1, 3, 7}, "0313-wagon-engine-fixes", "2026-10-15"), [1, 3])
        self.assertEqual([e.n for e in learnings.untaken(self.dir)], [2])
        self.assertEqual(learnings.untaken(self.dir, "y"), [])
        taken = {e.n: e.taken for e in learnings.read(self.dir)}
        plan = "2026-10-15 0313-wagon-engine-fixes"
        self.assertEqual(taken, {1: plan, 2: "", 3: plan})
        self.assertEqual(learnings.mark_taken(self.dir, {1}, "other", "2026-10-16"), [1])  # a later mark replaces it
        self.assertEqual(learnings.read(self.dir)[0].taken, "2026-10-16 other")
        self.assertEqual((self.dir / "learnings.md").read_text().count("**Taken:**"), 3)

    def test_mark_taken_without_a_file(self):
        self.assertEqual(learnings.mark_taken(self.dir, {1}), [])

    def test_the_hand_written_file_parses(self):
        (self.dir / "learnings.md").write_text(LEGACY)
        got = learnings.read(self.dir)
        self.assertEqual([e.n for e in got], [1, 2, 3])  # "Other surprises" is no entry
        self.assertEqual(got[0].at, "2026-10-14")
        self.assertEqual(got[0].slug, "The carrier's remote branch keeps a dead train")
        self.assertTrue(got[0].case.startswith("train 07") and got[0].case.endswith("Fixed by hand three times."))
        self.assertEqual([e.code for e in got], ["y", "y", "n"])
        self.assertTrue(got[1].rule.startswith("a car rides only with proof"))  # "**Rule** (the user's, ...):"
        self.assertEqual(len(learnings.untaken(self.dir)), 3)

    def test_a_new_entry_goes_after_the_hand_written_ones(self):
        (self.dir / "learnings.md").write_text(LEGACY)
        self.assertEqual(self.add("new one").n, 4)
        learnings.mark_taken(self.dir, {1, 4}, "0313", "2026-10-15")
        text = (self.dir / "learnings.md").read_text()
        self.assertTrue(text.startswith("# wagon-master learnings (hal2)"))  # no envelope forced on the old file
        self.assertIn("- **Code**: yes. engine.py should push the reset with a lease (engine foreman, wt 17).\n"
                      "**Taken:** 2026-10-15 0313\n", text)
        self.assertEqual([e.n for e in learnings.untaken(self.dir)], [2, 3])

    def test_extra_keys_are_kept(self):
        self.add(extra=[("Start", "2026-10-14 09:30Z"), ("Metric", "first-try green rate")])
        e = learnings.read(self.dir)[0]
        self.assertEqual((e.fields["start"], e.fields["metric"]), ("2026-10-14 09:30Z", "first-try green rate"))
        self.assertEqual(e.as_dict()["fields"]["metric"], "first-try green rate")

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = learnings.main(["--dir", str(self.dir), *args])
        return code, out.getvalue()

    def test_cli(self):
        code, out = self.run_cli("add", "--case", "Red train", "--cause", "a car", "--rule", "unhitch it",
                                 "--code", "y", "--field", "Start=2026-10-14")
        self.assertEqual((code, out), (0, "L1 red-train\n"))
        self.assertIn("L1 · ", self.run_cli("untaken")[1])
        self.assertEqual(self.run_cli("untaken", "--code", "n")[1], "")
        self.assertEqual(self.run_cli("rules")[1], "L1 red-train: unhitch it\n")
        self.assertIn('"slug": "red-train"', self.run_cli("untaken", "--json")[1])
        self.assertEqual(self.run_cli("mark-taken", "1", "--plan", "0313")[0], 0)
        self.assertEqual(self.run_cli("mark-taken", "9")[0], 1)
        self.assertEqual(self.run_cli("untaken")[1], "")
        self.assertIn("[taken]", self.run_cli("rules")[1])


if __name__ == "__main__":
    unittest.main()
