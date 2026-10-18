import unittest
from datetime import datetime, timedelta, timezone

import learn
import sources
from fake_cli import FakeCli
from transcripts import Message

PAIRSET = learn.load_pairs()
PAIRS = PAIRSET.pairs
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def stat(text, new, many=None):
    """The Stat of the pair `new` after counting `text` (a string or a list of strings)."""
    stats = learn.count(many if many is not None else [text], PAIRS)
    return next(s for s in stats if s.pair.new == new)


class PairsFile(unittest.TestCase):
    def test_every_regex_compiles_and_new_forms_match_their_word(self):
        for pair in PAIRS:
            self.assertTrue(learn._compile(pair.new_forms), pair.new)
            self.assertGreater(stat(pair.new + " 07", pair.new).new, 0, pair.new)  # field needs its number

    def test_every_old_form_has_an_example_that_counts(self):
        self.assertEqual(stat("we merge-to-main", "bring in").old, 1)

    def test_pair_is_a_known_shape(self):
        for pair in PAIRS:
            self.assertEqual(pair.since, "2026-10-13")
            self.assertTrue(pair.old_label)


class WholeWords(unittest.TestCase):
    def test_compounds_do_not_count_as_shot(self):
        for text in ("a screenshot of it", "the one-shot run", "a snapshot", "shot-list", "slideshot"):
            self.assertEqual(stat(text, "seed").old, 0, text)

    def test_shot_counts_with_inflection_and_case(self):
        self.assertEqual(stat("Shots and a shot.", "seed").old, 2)

    def test_slash_command_is_not_a_word(self):
        self.assertEqual(stat("then run /mtm now", "bring in").old, 0)
        self.assertEqual(stat("then run mtm now", "bring in").old, 1)

    def test_slash_between_words_still_counts(self):
        self.assertEqual(stat("shots/screens", "seed").old, 1)

    def test_hyphenated_longer_word_is_one_word(self):
        old_name = "mtm-fast" + "lane please"  # the skill's old name, spelt apart (plan 0360 D57)
        self.assertEqual(stat(old_name, "bring in").old, 0)
        self.assertEqual(stat(old_name, "smuggle").old, 1)

    def test_old_and_new_inflections(self):
        self.assertEqual((stat("brought in", "bring in").new, stat("seeds", "seed").new, stat("sowing", "sow").new,
                          stat("smuggled", "smuggle").new, stat("mucks out", "muck out").new,
                          stat("ticked it off", "tick off").new), (1, 1, 1, 1, 1, 1))
        self.assertEqual(stat("he landed on main", "bring in").old, 1)
        self.assertEqual(stat("shooting it", "sow").old, 1)

    def test_longest_stretch_wins(self):
        self.assertEqual(stat("a todo list", "daybook").old, 1)
        self.assertEqual(stat("a todo list", "chore").old, 0)
        self.assertEqual(stat("add a todo", "jot").old, 1)
        self.assertEqual(stat("add a todo", "chore").old, 0)
        self.assertEqual(stat("finish the todo", "tick off").old, 1)
        self.assertEqual(stat("the shotfile", "seed").old, 0)
        self.assertEqual(stat("the shotfile", "seedbag").old, 1)

    def test_worktree_pair_takes_slot_wt_and_the_new_field(self):
        s = stat("wt 07 and worktree 03 and slot 05", "field")
        self.assertEqual(s.old, 3)
        self.assertEqual(stat("field 07", "field").new, 1)
        self.assertEqual(stat("an input field", "field").new, 0)


class Ambiguous(unittest.TestCase):
    def test_vm_slot_is_ambiguous_not_old(self):
        s = stat("the VM slot is full", "field")
        self.assertEqual((s.old, s.ambiguous_count, s.ambiguous), (0, 1, {"slot": 1}))

    def test_git_worktree_branch_main_lead_task_watch(self):
        self.assertEqual(stat("git worktree add", "field").old, 0)
        self.assertEqual(stat("git worktree add", "field").ambiguous_count, 1)
        self.assertEqual(stat("on the branch main", "crop").ambiguous_count, 1)
        self.assertEqual(stat("on the branch main", "barn").ambiguous_count, 1)
        self.assertEqual(stat("the lead said", "foreman").ambiguous_count, 1)
        self.assertEqual(stat("a task", "chore").ambiguous_count, 1)
        self.assertEqual(stat("watch it", "lookout").ambiguous_count, 1)
        self.assertEqual(stat("a landing page", "bring in").ambiguous_count, 1)

    def test_harvest_is_no_longer_the_landing_and_keeps_its_name(self):
        s = stat("harvest 07 and brings 08 in", "bring in")  # the landing's word until 2026-10-13: ambiguous now
        self.assertEqual((s.old, s.new, s.ambiguous_count), (0, 1, 1))
        kept = {k.lower() for k in PAIRSET.keep_names}
        self.assertTrue({"harvest", "christen", "christening"} <= kept)
        words = [sources.FarmWord("harvest", "the foreman's part", "in force", "Activities")]
        self.assertEqual(learn.coverage_warnings(PAIRSET, words, [("christen", "christening"), ("landing", "bring in")]), [])

    def test_ambiguous_is_left_out_of_the_share(self):
        s = stat("", "bring in", ["a landing page", "mtm", "bring in"])
        self.assertEqual((s.old, s.new, s.ambiguous_count, s.share), (1, 1, 1, 0.5))

    def test_ambiguous_lines_say_what_and_why(self):
        lines = learn.ambiguous_lines(learn.count(["the VM slot", "a slot"], PAIRS))
        self.assertTrue(any('"slot" 2' in line and "VM or queue" in line for line in lines))
        self.assertTrue(any(line.startswith("note for field") for line in lines))


class Table(unittest.TestCase):
    def test_sorted_by_old_uses_and_unused_left_out(self):
        stats = learn.count(["shot shot shot", "mtm mtm", "merge queue", "bring in"], PAIRS)
        self.assertEqual([s.pair.new for s in learn.ranked(stats)][:3], ["seed", "bring in", "toll gate"])
        self.assertNotIn("steward", [s.pair.new for s in learn.ranked(stats)])

    def test_share_percent_in_the_table(self):
        text = learn.table(learn.count(["shot", "seed", "seed", "seed"], PAIRS))
        row = next(line for line in text.splitlines() if line.startswith("shot "))
        self.assertIn("75%", row)

    def test_dash_when_no_old_and_no_new(self):
        self.assertIn("-", learn.table(learn.count(["on a branch"], PAIRS)).splitlines()[1])

    def test_example_has_the_new_word_and_is_short(self):
        long_line = "x " * 80 + "please do the mtm of this work " + "y " * 80
        s = stat("", "bring in", [long_line])
        self.assertIn("bring in", s.example[1])
        self.assertNotIn("mtm", s.example[1])
        self.assertLessEqual(len(s.example[1]), 100)
        short = stat("please mtm this", "bring in")
        self.assertEqual(short.example[1], "please bring in this")

    def test_example_is_the_line_of_the_newest_message(self):
        old = Message("first mtm", NOW - timedelta(days=2), "p")
        new = Message("second mtm\nthird line", NOW, "p")
        s = stat("", "bring in", [new, old])
        self.assertEqual(s.example[1], "second bring in")

    def test_example_keeps_the_user_line_only(self):
        s = stat("", "seed", ["before\nthe shots here\nafter"])
        self.assertEqual(s.example[1], "the seeds here".replace("seeds", "seed"))


class TalkAboutTheWords(unittest.TestCase):
    """A message naming a pair with its old and its new word (a definition, a question) counts neither for it."""

    def test_old_and_new_word_of_one_pair_in_one_message_count_neither(self):
        text = "merge queue -> toll gate\nand shot stays"
        self.assertEqual((stat(text, "toll gate").old, stat(text, "toll gate").new), (0, 0))
        self.assertIsNone(stat(text, "toll gate").example)
        self.assertEqual(stat(text, "seed").old, 1)  # another pair of the same message still counts

    def test_the_two_words_in_two_messages_count_each(self):
        s = stat("", "toll gate", ["the merge queue", "the toll gate"])
        self.assertEqual((s.old, s.new), (1, 1))

    def test_ambiguous_forms_of_a_named_pair_still_count(self):
        s = stat("mtm is bring in, a landing", "bring in")
        self.assertEqual((s.old, s.new, s.ambiguous_count), (0, 0, 1))


class CleanupAndShootSkill(unittest.TestCase):
    def test_bare_cleanup_is_ambiguous_but_run_cleanup_and_worktree_cleanup_are_old(self):
        s = stat("it needs a manual cleanup", "muck out")
        self.assertEqual((s.old, s.ambiguous_count), (0, 1))
        self.assertEqual(stat("then run cleanup", "muck out").old, 1)
        self.assertEqual(stat("cleanup the worktrees", "muck out").old, 1)

    def test_the_shoot_skill_is_a_kept_name_not_an_old_word(self):
        self.assertEqual(stat("what does the shoot skill do", "sow").old, 0)
        self.assertEqual(stat("shoot shot 29", "sow").old, 1)


class Practise(unittest.TestCase):
    def test_three_words_most_old_uses_ties_by_lower_share(self):
        texts = ["shot " * 5, "mtm " * 3, "bring in", "fast" "lane " * 3, "merge queue", "merge queue", "toll gate"]
        top = [s.pair.new for s in learn.practise(learn.count(texts, PAIRS))]
        self.assertEqual(top, ["seed", "smuggle", "bring in"])  # smuggle 3 old, 0% before bring in 3 old, 25%

    def test_a_pair_never_used_or_used_only_new_is_left_out(self):
        top = [s.pair.new for s in learn.practise(learn.count(["bring it in", "a sow"], PAIRS))]
        self.assertEqual(top, [])

    def test_a_pair_that_stays_is_never_practised(self):
        top = [s.pair.new for s in learn.practise(learn.count(["watch " * 9], PAIRS))]
        self.assertEqual(top, [])

    def test_ambiguous_only_is_not_practised(self):
        self.assertEqual(learn.practise(learn.count(["the VM slot"], PAIRS)), [])


class Coverage(FakeCli):
    def test_sample_with_a_pair_for_each_word_has_no_warning(self):
        data = sources.load()  # the CLI's answers for fixtures/sources
        words = sources.farm_words(data)
        heads = sources.glossary_pairs(data)
        self.assertEqual(learn.coverage_warnings(PAIRSET, words, heads), [])
        self.assertEqual(heads, [("shot", "seed"), ("landing", "bring in")])
        for old, new in heads:  # the old word of a heading is matched by its pair
            pair = next(p for p in PAIRS if p.new.lower() == new.lower())
            self.assertTrue(learn._compile(list(pair.old) + [a[0] for a in pair.ambiguous]).search(old), (old, new))

    def test_a_farm_word_without_a_pair_warns_and_a_kept_name_does_not(self):
        words = [sources.FarmWord("scythe", "x", "in force", "Activities"),
                 sources.FarmWord("pause", "x", "in force", "Activities"),
                 sources.FarmWord("cockcrow", "x", "proposed, not chosen", "Activities")]
        warnings = learn.coverage_warnings(PAIRSET, words, [("cut", "reap")])
        self.assertEqual(len(warnings), 2)
        self.assertIn("scythe", warnings[0])
        self.assertIn("reap", warnings[1])

    def test_a_new_word_of_the_live_files_is_a_warning_of_learn_not_an_error(self):
        words = [sources.FarmWord("farmhouse", "x", "in force", "Places")]
        warnings = learn.coverage_warnings(PAIRSET, words, [("barn door", "toolshed")])
        self.assertEqual(warnings, ['farm word "farmhouse" (ontology: Places) has no pair in pairs.json',
                                    'glossary heading "barn door, toolshed" has no pair in pairs.json'])


if __name__ == "__main__":
    unittest.main()
