"""The foreman's and the servant's page (hal2 plan 0366, step 3), over test_state's fixture (field 02 runs plan 0042
with three steps, 10 holds a shot name, 1 holds nothing)."""

import os
import unittest
from pathlib import Path
from unittest import mock

import state
import view_foreman
import views
from test_state import Fixture

real = os.path.realpath
QUESTIONS = """---
type: Questions
---

# Questions

<!-- ## Q9 · 2026-01-01 · agent · open  (the format) -->

## Q1 · 2026-10-01 · agent · answered 2026-10-02

**Q:** Done already?

## Q2 · 2026-10-03 · agent · open

**Q:** Should the <b>bar</b> be green?
  a) yes
"""


class Foreman(Fixture):
    def page(self, field: str, role: str | None = None) -> tuple[str, list[dict]]:
        data = state.collect(str(self.main))
        ctx = {"repo": "proj", "checkout": field, "top": str(self.wt / field), "main": str(self.main)}
        return views.build(role or ("foreman" if int(field) < 30 else "servant"), data, ctx)

    def text(self, sections: list[dict]) -> str:
        return repr(sections)

    def test_the_registry_serves_foreman_and_servant(self):
        self.assertIs(views.VIEWS["foreman"], view_foreman.view)
        self.assertIs(views.VIEWS["servant"], view_foreman.view)

    def test_the_plan_its_progress_and_its_step_table(self):
        title, sections = self.page("02")
        self.assertEqual(title, "proj · foreman 02")
        by = {s["heading"]: s for s in sections}
        self.assertEqual(list(by), ["Plan 0042: the answer", "Progress", "Steps", "Next step", "Open questions"])
        self.assertEqual(by["Progress"]["bar"], [1, 3])
        self.assertEqual(by["Progress"]["text"], "1 of 3 steps done")
        steps = by["Steps"]
        self.assertEqual(steps["columns"], ["#", "Step", "Done when", "Status"])
        self.assertEqual([r[:2] for r in steps["rows"]], [["1", "one"], ["2", "two"], ["3", "three"]])
        self.assertEqual(steps["marked"], [1])
        self.assertEqual(by["Next step"]["text"], "2: two Done when: x")
        self.assertEqual(by["Open questions"]["empty"], "No open questions.")

    def test_description_landing_and_queue_lines(self):
        (self.plan_dir / "plan.md").write_text(
            '---\ntype: Plan\nschema: 1\nlanding: auto\ndescription: "What 42 brings in"\n---\n\n' + (self.plan_dir / "plan.md").read_text())
        for queue, want in ((None, "not in the merge queue"),
                            ([{"slot": "02", "worktree": real(self.wt / "02"), "position": 1, "holding": True, "state": "x"}],
                             "holds the toll gate"),
                            ([{"slot": "02", "worktree": real(self.wt / "02"), "position": 3, "holding": False, "state": "x"}],
                             "position 3")):
            self.set_tools(queue=queue)
            items = self.page("02")[1][0]["items"]
            self.assertEqual(items[0], "What 42 brings in")
            self.assertEqual(items[1], "Landing: auto (wait)")
            self.assertIn(want, items[2])

    def test_smuggle_mode_shows_in_the_queue_line(self):
        self.set_tools(mode={"mode": "smuggle"})
        self.assertIn("smuggle mode", self.page("02")[1][0]["items"][-1])

    def test_a_finished_plan_has_no_next_step(self):
        text = (self.plan_dir / "plan.md").read_text().replace("| next |", "| done |").replace("|  |", "| done |")
        (self.plan_dir / "plan.md").write_text(text.replace("three | x | |", "three | x | done |"))
        by = {s["heading"]: s for s in self.page("02")[1]}
        self.assertEqual(by["Progress"]["bar"], [3, 3])
        self.assertEqual(by["Next step"]["empty"], "Every step is done.")
        self.assertNotIn("text", by["Next step"])
        self.assertEqual(by["Steps"]["marked"], [])

    def test_open_questions_are_listed_and_answered_ones_are_not(self):
        (self.plan_dir / "questions.md").write_text(QUESTIONS)
        by = {s["heading"]: s for s in self.page("02")[1]}
        self.assertEqual(by["Open questions"]["items"], ["Q2: Should the <b>bar</b> be green?"])

    def test_the_page_escapes_what_the_plan_says(self):
        (self.plan_dir / "questions.md").write_text(QUESTIONS)
        title, sections = self.page("02")
        import page
        out = page.render(title, sections)
        self.assertNotIn("<b>bar</b>", out)
        self.assertIn("&lt;b&gt;bar&lt;/b&gt;", out)
        self.assertIn('<div class="bar"><span style="width:33%"></span></div>', out)

    def test_without_the_plan_skill_the_table_is_read_by_hand(self):
        with mock.patch.object(view_foreman, "plan_module", return_value=None):
            by = {s["heading"]: s for s in self.page("02")[1]}
        self.assertEqual(by["Progress"]["bar"], [1, 3])
        self.assertEqual(by["Steps"]["marked"], [1])
        self.assertEqual(by["Plan 0042: the answer"]["items"][-1], "Queue: field 02 not in the merge queue")

    def test_a_failing_plan_skill_falls_back_too(self):
        module = mock.Mock()
        module.describe_safe.side_effect = RuntimeError("boom")
        with mock.patch.object(view_foreman, "plan_module", return_value=module):
            by = {s["heading"]: s for s in self.page("02")[1]}
        self.assertEqual(by["Progress"]["bar"], [1, 3])

    def test_a_servant_shows_its_foremans_plan(self):
        (self.wt / "10/plans/LEAD").write_text("02 0042-the-answer 3\n")
        title, sections = self.page("10", "servant")
        self.assertEqual(title, "proj · servant 10")
        self.assertEqual(sections[0]["heading"], "Plan 0042: the answer")
        self.assertIn("servant of 02, working step 3", sections[0]["items"])
        self.assertEqual(sections[1]["bar"], [1, 3])

    def test_a_servant_whose_foreman_is_gone_shows_its_own_state(self):
        (self.wt / "10/plans/LEAD").write_text("07 0042-the-answer 3\n")
        title, sections = self.page("10", "servant")
        self.assertEqual(sections[0]["heading"], "Plan")
        self.assertIn("my-shots/3/fix-the-thing", sections[0]["empty"])

    def test_no_plan_is_an_empty_state(self):
        title, sections = self.page("1", "foreman")
        self.assertEqual(sections, [{"heading": "Plan", "empty": "No plan in this field."}])

    def test_a_shot_in_current_plan_is_named(self):
        sections = self.page("10", "foreman")[1]
        self.assertEqual(sections[0]["empty"], "No plan in this field. Its CURRENT_PLAN pointer says: my-shots/3/fix-the-thing")

    def test_a_checkout_that_is_no_worktree_row(self):
        data = state.collect(str(self.main))
        ctx = {"repo": "proj", "checkout": "99", "top": "/nowhere", "main": str(self.main)}
        sections = views.build("foreman", data, ctx)[1]
        self.assertIn("not one of the repository's worktrees", sections[0]["empty"])

    def test_the_cli_writes_the_foreman_page(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(state.main(["--repo", str(self.wt / "02"), "--no-open"]), 0)
        text = Path(buf.getvalue().strip()).read_text(encoding="utf-8")
        for want in ("<h1>proj · foreman 02</h1>", "<th>Done when</th>", "<td>two</td>", "Next step"):
            self.assertIn(want, text)

    def test_a_bar_clamps_and_ignores_a_bad_total(self):
        import page
        for bar, want in (([1, 4], "25%"), ([9, 4], "100%"), ([0, 0], None), (["x", 2], None), (None, None)):
            out = page.render("t", [{"heading": "p", "bar": bar, "text": "t"}])
            if want:
                self.assertIn(f'style="width:{want}"', out)
            else:
                self.assertNotIn("class=\"bar\"", out)


if __name__ == "__main__":
    unittest.main()
