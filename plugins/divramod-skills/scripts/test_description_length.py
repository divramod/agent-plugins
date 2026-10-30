#!/usr/bin/env python3
"""The listing rule of plan 0485 for the three role skills the tollman tick wakes: description at most 400 characters."""
import re
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
BOUND = 400
CHECKED = {
    "roles/tollman": ("/tollman", "tollman", "Zöllner", "wagon train", "hitch"),
    "roles/farmer": ("/farmer", "farmer", "watch CI", "dependabot"),
    "actions/prune": ("/prune", "prune the fields", "free disk space"),
}


def description(skill: str) -> str:
    text = (SKILLS / skill / "SKILL.md").read_text()
    return re.search(r"^description: (.*)$", text, re.M).group(1)


class TestDescriptionLength(unittest.TestCase):
    def test_at_most_400_characters(self):
        for skill in CHECKED:
            with self.subTest(skill=skill):
                self.assertLessEqual(len(description(skill)), BOUND)

    def test_trigger_words_kept(self):
        for skill, words in CHECKED.items():
            for word in words:
                with self.subTest(skill=skill, word=word):
                    self.assertIn(word, description(skill))


if __name__ == "__main__":
    unittest.main()
