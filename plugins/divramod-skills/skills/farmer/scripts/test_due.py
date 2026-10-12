import datetime as dt
import unittest

import due

ROLE = """---
duties:
  mtm: "*/15 * * * *"
  ci: "0 * * * *"
servant_limit: 5
notify: every-round
---

# x

## Tasks

### n8n stays up

- **Cron**: `*/15 * * * *`
- **Check**: curl

### Disabled tests come back

- **Cron**: `7 9 * * *`

## Notes

### not a task
"""


class Cron(unittest.TestCase):
    def test_fields_lists_ranges_steps_and_sunday_as_7(self):
        self.assertEqual(due.parse_field("*/15", 0, 59), {0, 15, 30, 45})
        self.assertEqual(due.parse_field("1-5", 0, 7), {1, 2, 3, 4, 5})
        self.assertEqual(due.parse_field("4-59/15", 0, 59), {4, 19, 34, 49})
        self.assertEqual(due.parse_field("0,30", 0, 59), {0, 30})
        self.assertIn(0, due.parse_cron("0 9 * * 7")[4])
        for bad in ("* * * *", "61 * * * *", "every hour", "*/0 * * * *"):
            with self.assertRaises(ValueError, msg=bad):
                due.parse_cron(bad)

    def test_last_fire_and_due(self):
        now = dt.datetime(2026, 10, 3, 10, 20)  # a Saturday
        self.assertEqual(due.last_fire("*/15 * * * *", now), dt.datetime(2026, 10, 3, 10, 15))
        self.assertEqual(due.last_fire("7 9 * * *", now), dt.datetime(2026, 10, 3, 9, 7))
        self.assertEqual(due.last_fire("0 8 * * 1-5", now), dt.datetime(2026, 10, 2, 8, 0))
        self.assertTrue(due.is_due("*/15 * * * *", dt.datetime(2026, 10, 3, 10, 14), now))
        self.assertFalse(due.is_due("*/15 * * * *", dt.datetime(2026, 10, 3, 10, 16), now))
        self.assertTrue(due.is_due("7 9 * * *", None, now))
        self.assertFalse(due.is_due("7 9 * * *", dt.datetime(2026, 10, 3, 9, 30), now))

    def test_loop_cron_follows_the_shortest_interval(self):
        self.assertEqual(due.loop_cron({"a": "*/15 * * * *", "b": "0 * * * *"}), "7-59/15 * * * *")
        self.assertEqual(due.loop_cron({"a": "* * * * *"}), "2-59/5 * * * *")
        self.assertEqual(due.loop_cron({"a": "7 9 * * *"}), "4 * * * *")


class Role(unittest.TestCase):
    def test_only_what_is_opted_in(self):
        items, settings, problems = due.schedule(ROLE)
        self.assertEqual(problems, [])
        self.assertEqual(items, {"duty:mtm": "*/15 * * * *", "duty:ci": "0 * * * *",
                                 "task:n8n stays up": "*/15 * * * *", "task:Disabled tests come back": "7 9 * * *"})
        self.assertEqual(settings, {"servant_limit": 5, "notify": "every-round", "servant_model": "opus",
                                    "servant_effort": "medium"})

    def test_nothing_implicit_missing_settings_and_crons_are_problems(self):
        _, _, problems = due.schedule("---\nduties:\n  boss: \"x\"\n---\n\n## Tasks\n\n### t\n\n- **Check**: a\n")
        text = "\n".join(problems)
        for part in ("unknown duty 'boss'", "task 't' has no", "notify", "duty:boss"):
            self.assertIn(part, text)
        self.assertNotIn("servant_limit", text, "servant_limit defaults to auto")

    def test_servant_limit_is_auto_by_default_or_a_number(self):
        self.assertEqual(due.schedule(ROLE.replace("servant_limit: 5\n", ""))[1]["servant_limit"], "auto")
        self.assertEqual(due.schedule(ROLE.replace("servant_limit: 5", "servant_limit: auto"))[1]["servant_limit"],
                         "auto")
        problems = due.schedule(ROLE.replace("servant_limit: 5", "servant_limit: lots"))[2]
        self.assertIn("`servant_limit:` is `auto` or a number", problems)
        self.assertEqual(due.schedule("")[0], {})

    def test_the_servants_model_and_effort_default_to_opus_medium_or_are_named(self):
        # Skills plan 0016 (D15): every servant starts at an explicit model and effort.
        named = ROLE.replace("servant_limit: 5", "servant_limit: 5\nservant_model: claude-opus-5-5\nservant_effort: high")
        _, settings, problems = due.schedule(named)
        self.assertEqual((settings["servant_model"], settings["servant_effort"], problems),
                         ("claude-opus-5-5", "high", []))
        bad = ROLE.replace("servant_limit: 5", "servant_limit: 5\nservant_model: Opus 5\nservant_effort: huge")
        text = "\n".join(due.schedule(bad)[2])
        self.assertIn("`servant_model:` is a model alias", text)
        self.assertIn("`servant_effort:` is one of low, medium, high, xhigh, max", text)


if __name__ == "__main__":
    unittest.main()
