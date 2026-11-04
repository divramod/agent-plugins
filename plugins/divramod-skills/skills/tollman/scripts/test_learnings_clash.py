"""Hal2 plan 0610 step 8 (D20): the tollman's handoff against its in-force learnings (learnings_clash.py). The replay is
field 79's finding: handoff.md said "never --by-user myself" and "never unhitch" while learnings printed after it (L31,
L241) said the opposite, and the model followed what it read last. Archived and dropped entries are out; a clashing
entry is tagged by `learnings.py rules`; `handoff --clear` refuses and `act` warns, each naming the lines."""
# enforces .adr/deterministic-first.md

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (puts the farmer skill's scripts on the path)
import handoff
import learnings
import learnings_clash as clash
import role_cli
import tollman
from test_tollman import WIRING, Field

HANDOFF = """# tollman handoff

## DO FIRST

- Never unhitch a finished wagon. A red light check gets a fix order in the train.
- Earlier: farmer's orders = the user's; never --by-user myself; autonomy on.

## Merge trains

- A formed train stays frozen; a wagon hitched later waits for the next train.
"""


class Folder(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def learn(self, rule, slug="a rule", **extra):
        return learnings.add(self.dir, "case", "cause", rule, "n", slug=slug, at="2026-11-04 09:00Z",
                             extra=list(extra.items()))

    def found(self, handoff_text):
        return [(c.topic, c.entry) for c in clash.check(handoff_text, learnings.read(self.dir))]


class Pairs(Folder):
    def test_never_unhitch_against_an_in_force_unhitch(self):
        """L31's wording: "unhitch only what the code itself rejects"."""
        self.learn("never shape a train by hand: no unhitch to make room; unhitch only what the code itself rejects")
        self.assertEqual(self.found("- Never unhitch a finished wagon.\n"), [("unhitch", 1)])
        self.assertEqual(self.found("- unhitch the car with the file:line.\n"), [("unhitch", 1)], "both stances in L1")

    def test_an_order_in_the_handoff_against_a_never_in_the_learnings(self):
        self.learn("Never unhitch (by code or hand), never tell a foreman to unhitch or re-hitch.")
        self.assertEqual(self.found("Unhitch the red car, then form.\n"), [("unhitch", 1)])
        self.assertEqual(self.found("Tell the foreman to re-hitch.\n"), [("unhitch", 1)])

    def test_the_same_stance_or_another_topic_is_no_clash(self):
        self.learn("Never unhitch a finished wagon.")
        self.assertEqual(self.found("- Never unhitch a finished wagon.\n- Restock and form the train.\n"), [])

    def test_a_never_with_a_condition_and_an_order_next_to_the_users_words_are_neutral(self):
        self.learn("Never unhitch unless the user says so.", "cond")
        self.assertEqual(self.found("Unhitch the car.\n"), [])
        self.learn("unhitch field 09, the user's own command of 2026-11-04", "user")
        self.assertEqual(self.found("Never unhitch a finished wagon.\n"), [])

    def test_by_user_myself_against_the_users_dissolve_order(self):
        """L241: breakup --by-user, the user's own command; the handoff: never --by-user myself."""
        self.learn("dissolve train 51 (engine.py breakup --by-user, the user's own command of 2026-11-04)", "dissolve")
        self.assertEqual(self.found("Earlier: farmer's orders = the user's; never --by-user myself; autonomy on.\n"),
                         [("by-user", 1)])
        self.assertEqual(self.found("Pass --by-user only for the user's command.\n"), [])

    def test_a_frozen_train_against_a_later_hitch_that_joins(self):
        self.learn("a wagon that hitches while a train stands joins the open train until its push starts", "join")
        self.assertEqual(self.found("A formed train stays frozen; a later hitch waits for the next train.\n"),
                         [("frozen", 1)])

    def test_only_in_force_entries_count(self):
        self.learn("unhitch the car with the file:line", "old")
        self.learn("unhitch a stale hitch", "dropped", Status="dropped")
        self.learn("unhitch the other", "kept")
        import learnings_archive
        learnings_archive.archive(self.dir, {1}, "plan 0610")
        self.assertEqual(self.found("Never unhitch a finished wagon.\n"), [("unhitch", 3)])

    def test_the_whole_handoff_is_read_in_items_and_sentences(self):
        self.learn("unhitch the culprit", "u")
        self.learn("engine.py breakup --by-user, the user's own command", "b")
        self.learn("a later hitch joins the open train", "j")
        got = clash.check(HANDOFF, learnings.read(self.dir))
        self.assertEqual([(c.topic, c.line, c.entry) for c in got],
                         [("unhitch", 5, 1), ("by-user", 6, 2), ("frozen", 10, 3)])
        text = clash.report(got)
        self.assertIn('handoff.md:5 [unhitch] "Never unhitch a finished wagon." against L1 u', text)
        self.assertIn("handoff.md:10 [frozen]", text)


class Hard(Folder):
    def test_an_entry_against_the_users_hard_rules(self):
        """D5 never unhitch; D1 with D17: a hitched wagon rides, a later hitch joins the open train."""
        e = self.learn("unhitch the car with the file:line; the rest rides")
        self.assertEqual(len(clash.hard(e)), 1)
        self.assertIn("D5", clash.hard(e)[0])
        self.assertIn("D1", clash.hard(self.learn("a formed train stays frozen"))[0])
        self.assertEqual(clash.hard(self.learn("Never unhitch (by code or hand); every red is a fix order")), [])
        self.assertEqual(clash.hard(self.learn("unhitch only on the user's own word, --by-user")), [])

    def test_rules_tags_the_clashing_entry(self):
        self.learn("never shape a train by hand; unhitch only what the code rejects", "l31")
        self.learn("a red is a fix order in the train", "fine")
        lines = learnings.rules_text(self.dir).splitlines()
        self.assertIn("[clashes with D5 hitch-is-forever", lines[0])
        self.assertTrue(lines[1].endswith("a red is a fix order in the train"), lines[1])
        import learnings_archive
        learnings_archive.archive(self.dir, {1}, "plan 0610")
        self.assertNotIn("clashes", learnings.rules_text(self.dir))


class Cli(Field):
    def setUp(self):
        super().setUp()
        self.main = str(self.main)
        self.file = handoff.path(self.main, WIRING)
        self.file.write_text(HANDOFF)
        self.folder = self.file.parent

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tollman.main([*argv, "--repo", str(self.wm)])
        return code, out.getvalue(), err.getvalue()

    def test_clear_refuses_and_names_the_lines_then_passes_once_the_learning_is_archived(self):
        learnings.add(self.folder, "c", "c", "unhitch the culprit", "n", slug="unhitch-culprit")
        with mock.patch.object(role_cli, "run_handoff", return_value=0) as run:
            code, out, err = self.run_cli("handoff", "--clear")
            self.assertEqual((code, run.call_count), (1, 0))
            self.assertIn("handoff.md:5 [unhitch]", err)
            self.assertIn("against L1 unhitch-culprit", err)
            import learnings_archive
            learnings_archive.archive(self.folder, {1}, "plan 0610")
            self.assertEqual(self.run_cli("handoff", "--clear")[0], 0)
            self.assertEqual(run.call_count, 1)

    def test_act_warns_and_goes_on_other_calls_do_not_check(self):
        learnings.add(self.folder, "c", "c", "unhitch the culprit", "n", slug="unhitch-culprit")
        with mock.patch.object(role_cli, "run_wake", return_value=0) as run:
            code, out, err = self.run_cli("act")
            self.assertEqual((code, run.call_count), (0, 1))
            self.assertIn("contradicts in-force learnings", err)
            self.assertNotIn("contradicts", self.run_cli("act", "--json")[2])
        self.assertNotIn("contradicts", self.run_cli("handoff")[2])

    def test_no_handoff_no_clash(self):
        self.file.unlink()
        self.assertEqual(clash.guard(self.file, self.folder), "")


if __name__ == "__main__":
    unittest.main()
