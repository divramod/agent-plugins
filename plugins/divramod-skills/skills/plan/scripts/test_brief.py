"""brief.py: a plan's Brief section, its placeholders and the `plan-brief-filled` problems."""
import unittest

import brief

FILLED = """# Plan 0001: x

## Goal

A goal.

## Brief

- In: the plan delivers a Brief
- Out: the /seed skill
- Must: a Brief "in every plan";
  one that is short
- Proof: `python3 -m unittest`

## Context

- Seed: skill-plan#3
- a link
"""

TEMPLATE = """## Brief

- In: <what this plan delivers>
- Out: <what it leaves alone>
- Must: <each requirement one line, the user's words quoted>
- Proof: <the command or the UAT checks that show the whole works>

## Context

- Seed: <seedbag>#<n>
"""


class ParseTest(unittest.TestCase):
    def test_the_four_labelled_lines_and_a_continuation(self):
        self.assertEqual(brief.parse(FILLED), {
            "In": "the plan delivers a Brief", "Out": "the /seed skill",
            "Must": 'a Brief "in every plan"; one that is short', "Proof": "`python3 -m unittest`"})

    def test_a_plan_without_the_section_has_none(self):
        self.assertIsNone(brief.parse("# Plan\n\n## Goal\n\nx\n"))
        self.assertIsNone(brief.filled("# Plan\n\n## Goal\n\nx\n"))

    def test_a_missing_label_is_empty_and_the_section_ends_at_the_next_heading(self):
        values = brief.parse("## Brief\n\n- In: a\n\n## Steps\n\n- Out: not of the brief\n")
        self.assertEqual(values, {"In": "a", "Out": "", "Must": "", "Proof": ""})

    def test_filled_turns_placeholders_into_empty_strings(self):
        self.assertEqual(brief.filled(TEMPLATE), {label: "" for label in brief.LABELS})
        self.assertEqual(brief.filled(FILLED)["Out"], "the /seed skill")

    def test_placeholders(self):
        self.assertTrue(brief.is_placeholder("<what it leaves alone>"))
        self.assertTrue(brief.is_placeholder("  "))
        self.assertFalse(brief.is_placeholder("nothing <else>"))
        self.assertFalse(brief.is_placeholder("the /seed skill"))

    def test_the_seed_line(self):
        self.assertEqual(brief.seed(FILLED), "skill-plan#3")
        self.assertEqual(brief.seed(TEMPLATE), "<seedbag>#<n>")
        self.assertIsNone(brief.seed("## Context\n\n- a link\n"))
        self.assertTrue(brief.seed_placeholder("<seedbag>#<n>"))
        self.assertFalse(brief.seed_placeholder("skill-plan#3"))


class ProblemsTest(unittest.TestCase):
    def test_a_filled_brief_and_seed_pass(self):
        self.assertEqual(brief.problems(FILLED, "plans/0001-x/plan.md"), [])

    def test_the_template_reports_out_proof_and_the_seed_line(self):
        found = brief.problems(TEMPLATE, "plans/0001-x/plan.md")
        self.assertEqual(len(found), 3)
        self.assertTrue(all(line.startswith("plans/0001-x/plan.md: ") and line.endswith("(plan-brief-filled)")
                            for line in found))
        self.assertIn("Out", found[0])
        self.assertIn("Proof", found[1])
        self.assertIn("Seed", found[2])

    def test_in_and_must_may_stay_open_but_an_empty_out_is_reported(self):
        text = FILLED.replace("- Out: the /seed skill", "- Out:").replace("- In: the plan delivers a Brief", "- In: <x>")
        self.assertEqual(len(brief.problems(text, "p")), 1)
        self.assertIn("Out", brief.problems(text, "p")[0])

    def test_a_plan_without_the_section_or_a_done_plan_passes(self):
        self.assertEqual(brief.problems("# Plan\n\n## Goal\n\nx\n", "p"), [])
        self.assertEqual(brief.problems(TEMPLATE, "p", done=True), [])

    def test_a_deleted_seed_line_passes(self):
        self.assertEqual(brief.problems(FILLED.replace("- Seed: skill-plan#3\n", ""), "p"), [])


if __name__ == "__main__":
    unittest.main()
