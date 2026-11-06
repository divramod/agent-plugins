#!/usr/bin/env python3
"""The skill listing rule (README's Rules, "Skill listing"; plans 0480 and 0485): every model-invocable skill's
description at most 400 characters as listed and free of `<>`, the listing at most 25,000 characters in all, the
shortcuts in the listing (plan 0681), and the trigger words of the checked skills kept."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skill_listing  # noqa: E402

BOUND = skill_listing.BOUND
GOAL = skill_listing.GOAL


# The shortcuts are model-invocable since plan 0681 (a session may call Skill(mfm)), so they are listed.
SHORTCUTS = frozenset({
    'shortcuts/c', 'shortcuts/d', 'shortcuts/daily', 'shortcuts/gp', 'shortcuts/h', 'shortcuts/hv',
    'shortcuts/mfm', 'shortcuts/mtm', 'shortcuts/q', 'shortcuts/s', 'shortcuts/uat',
})

# Trigger words a description must keep: plan 0480's three, then the ten skills used most in the user's transcripts
# of 2026-10-17..31 (typed slash commands plus the Skill tool's calls: handoff 912, foreman 572, merge-from-main 515,
# merge-to-main 389, pause 173, plan 161, smuggle 80, continue 74, grill-plan 72, cleanup 54).
CHECKED = {
    "roles/tollman": ("/tollman", "tollman", "Zöllner", "wagon train", "hitch"),
    "roles/farmer": ("/farmer", "farmer", "watch CI", "dependabot"),
    "actions/prune": ("/prune", "prune the fields", "free disk space"),
    "roles/foreman": ("/foreman", "foreman", "fm", "Vorarbeiter", "running a plan"),
    "actions/merge-from-main": ("/mfm", "merge from main", "update the worktree with main"),
    "actions/handoff": ("/handoff", "hand off", "/continue", "continue"),
    "actions/merge-to-main": ("/mtm", "merge to main", "land this worktree"),
    "actions/pause": ("/pause", "pause", "stop everything for now"),
    "actions/plan": ("/plan", "plan a feature", "next on the plan", "finishes a step"),
    "actions/smuggle": ("/smuggle", "smuggle", "land without CI", "CI is down"),
    "actions/continue": ("/continue", "continue", "resume", "unpause"),
    "actions/grill-plan": ("/grill-plan", "grill", "stress-test", "poke holes"),
    "actions/cleanup": ("/cleanup", "clean the worktree", "delete build artifacts", "free disk space"),
}

SKILLS = {s.path: s for s in skill_listing.read()}


def listed():
    return [s for s in SKILLS.values() if not s.user_only]


class TestDescriptionLength(unittest.TestCase):
    def test_at_most_400_characters(self):
        for skill in listed():
            with self.subTest(skill=skill.path):
                self.assertLessEqual(len(skill.listed), BOUND)

    def test_no_angle_brackets(self):
        for skill in listed():
            with self.subTest(skill=skill.path):
                self.assertNotRegex(skill.description, "[<>]")

    def test_listing_total_within_goal(self):
        self.assertLessEqual(skill_listing.total(list(SKILLS.values())), GOAL)

    def test_shortcuts_listed(self):
        for path in SHORTCUTS:
            with self.subTest(skill=path):
                self.assertFalse(SKILLS[path].user_only)

    def test_trigger_words_kept(self):
        for skill, words in CHECKED.items():
            for word in words:
                with self.subTest(skill=skill, word=word):
                    self.assertIn(word, SKILLS[skill].description)


class TestCount(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write(self, rel: str, front: str):
        folder = self.root / rel
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"---\n{front}---\n\n# {folder.name}\n")

    def test_counts_name_and_listed_description(self):
        self.write("actions/alpha", "name: alpha\ndescription: Use for <x> and y.\n")
        self.write("roles/beta", 'name: beta\ndescription: "Quoted: yes."\n')
        self.write("shortcuts/c", "name: c\ndescription: Alias.\ndisable-model-invocation: true\n")
        skills = {s.path: s for s in skill_listing.read(self.root)}
        self.assertEqual(skills["actions/alpha"].listed, "Use for &lt;x&gt; and y.")
        self.assertEqual(skills["actions/alpha"].chars, len("alpha") + len("Use for &lt;x&gt; and y."))
        self.assertEqual(skills["roles/beta"].description, "Quoted: yes.")
        self.assertTrue(skills["shortcuts/c"].user_only)
        self.assertEqual(skills["shortcuts/c"].chars, 0)
        self.assertEqual(skill_listing.total(list(skills.values())), skills["actions/alpha"].chars + 4 + 12)

    def test_report_lists_per_skill_and_total(self):
        self.write("alpha", "name: alpha\ndescription: " + "x" * (BOUND + 1) + "\n")
        self.write("c", "name: c\ndescription: Alias.\ndisable-model-invocation: true\n")
        rep = skill_listing.report(skill_listing.read(self.root))
        self.assertEqual(rep["schema"], 1)
        self.assertEqual(rep["total"], 5 + BOUND + 1)
        self.assertEqual(rep["skills"], [{"path": "alpha", "name": "alpha", "chars": 5 + BOUND + 1,
                                          "description": BOUND + 1, "over": True}])
        self.assertEqual(rep["user_only"], ["c"])
        self.assertIn(f"total: {5 + BOUND + 1:,} characters", skill_listing.text(rep))

    def test_strict_exits_1_over_the_goal(self):
        self.write("alpha", "name: alpha\ndescription: short\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(skill_listing.main(["--root", str(self.root), "--strict"]), 0)
            self.write("beta", "name: beta\ndescription: " + "x" * (GOAL + 1) + "\n")
            self.assertEqual(skill_listing.main(["--root", str(self.root), "--strict"]), 1)
            self.assertEqual(skill_listing.main(["--root", str(self.root)]), 0)


if __name__ == "__main__":
    unittest.main()
