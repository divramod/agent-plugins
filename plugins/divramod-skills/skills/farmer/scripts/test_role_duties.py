"""role_duties.py: a role skill's `## Duties`, overridden and extended by a repository's ROLE.md (plan 0360 D27, D73)."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import role_duties

SKILL = """---
name: steward
description: x
---

# steward

## Duties

### answer: answer the user
Answers first, in words.
Then carries on.

### daybook
Keeps the daybook.

```
### not-a-duty
## Duties
```

## Rules

### no-duty-here
Not a duty: another section.
"""

ROLE = """---
duties:
  answer: "*/5 * * * *"
---

# a repo's steward

## Priorities

### first
Not a duty.

## Duties

### daybook
This repository keeps no daybook.

### deploys
Watches the deploys.

## Tasks

### n8n stays up
A task, not a duty.
"""


class Unit(unittest.TestCase):
    """A scratch skills unit with the role skills `steward` and `farmer` under skills/roles/."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "unit/.claude-plugin").mkdir(parents=True)
        for role, text in (("steward", SKILL), ("farmer", SKILL.replace("steward", "farmer"))):
            (self.tmp / f"unit/skills/roles/{role}").mkdir(parents=True)
            (self.tmp / f"unit/skills/roles/{role}/SKILL.md").write_text(text)
        (self.tmp / "unit/skills/actions/plan").mkdir(parents=True)
        (self.tmp / "unit/skills/actions/plan/SKILL.md").write_text("---\nname: plan\n---\n")
        self.start = self.tmp / "unit/skills/roles/farmer/scripts/role_duties.py"
        self.repo = self.tmp / "repo"
        (self.repo / "roles/steward").mkdir(parents=True)

    def duties(self, role="steward", repo=None):
        return role_duties.duties(role, repo, start=self.start)

    def test_the_skill_alone(self):
        found = self.duties()
        self.assertEqual([(d.id, d.source) for d in found], [("answer", "skill"), ("daybook", "skill")])
        self.assertEqual(found[0].title, "answer the user")
        self.assertEqual(found[0].text, "Answers first, in words.\nThen carries on.")
        self.assertEqual(found[0].first_line, "Answers first, in words.")

    def test_a_role_md_overrides_by_id_and_extends(self):
        (self.repo / "roles/steward/ROLE.md").write_text(ROLE)
        found = self.duties(repo=self.repo)
        self.assertEqual([(d.id, d.source) for d in found],
                         [("answer", "skill"), ("daybook", "override"), ("deploys", "extension")])
        self.assertEqual(found[1].text, "This repository keeps no daybook.")
        self.assertEqual(found[2].text, "Watches the deploys.")

    def test_a_role_md_without_duties_leaves_the_skill_s_list(self):
        (self.repo / "roles/steward/ROLE.md").write_text(ROLE.split("## Duties")[0])
        self.assertEqual(self.duties(repo=self.repo), self.duties())
        self.assertEqual(self.duties(repo=self.tmp / "no-role-file"), self.duties())

    def test_headings_in_a_code_fence_and_other_sections_are_ignored(self):
        ids = [d.id for d in self.duties()]
        self.assertNotIn("not-a-duty", ids)
        self.assertNotIn("no-duty-here", ids)
        self.assertNotIn("first", [d.id for d in self.duties(repo=self.repo)])

    def test_a_heading_that_is_no_id_is_refused(self):
        with self.assertRaises(role_duties.DutiesError):
            role_duties.parse("## Duties\n\n### Not An Id\ntext\n", "x")
        with self.assertRaises(role_duties.DutiesError):
            role_duties.parse("## Duties\n\n### a\n\n### a\n", "x")

    def test_an_unknown_role(self):
        with self.assertRaises(KeyError):
            self.duties("plan")  # a skill, but none of roles/
        self.assertEqual(role_duties.known_roles(self.start), ["farmer", "steward"])


class Cli(unittest.TestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = role_duties.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_unknown_role_exits_2_naming_the_known(self):
        code, _, err = self.run_main("no-such-role")
        self.assertEqual(code, 2)
        self.assertIn("known: ", err)
        for role in ("farmer", "foreman", "lord", "mayor", "pope", "servant", "steward", "tollman"):
            self.assertIn(role, err)

    def test_every_role_skill_has_duties(self):
        for role in role_duties.known_roles():
            with self.subTest(role=role):
                self.assertTrue(role_duties.duties(role), f"{role} lists no duties")

    def test_the_upper_roles_have_one_state_duty(self):
        for role in ("mayor", "lord", "pope"):
            with self.subTest(role=role):
                found = role_duties.duties(role)
                self.assertIn("state", [d.id for d in found])
                self.assertEqual({d.source for d in found}, {"skill"})
        for role in ("lord", "pope"):
            self.assertEqual([d.id for d in role_duties.duties(role)], ["state"])

    def test_json_shape(self):
        code, out, _ = self.run_main("steward", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(set(data), {"role", "skill", "role_file", "duties"})
        self.assertEqual(data["role"], "steward")
        self.assertIsNone(data["role_file"])
        self.assertTrue(data["duties"])
        self.assertEqual(set(data["duties"][0]), {"id", "title", "text", "source"})
        self.assertEqual({d["source"] for d in data["duties"]}, {"skill"})

    def test_the_plain_list(self):
        code, out, _ = self.run_main("farmer")
        self.assertEqual(code, 0)
        self.assertTrue(out.splitlines()[0].split()[1] == "skill", out)


if __name__ == "__main__":
    unittest.main()
