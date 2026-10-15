"""names.py: a plan name has at most four words, a research plan's `research-` not counted."""
import subprocess
import tempfile
import unittest
from pathlib import Path

import names


def slug_of(path: Path) -> str:
    return path.parent.name


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, check=True,
                   capture_output=True)


class WordsTest(unittest.TestCase):
    def test_words_of_a_title_and_of_a_numbered_slug(self):
        self.assertEqual(names.words("Brief and sprout"), ["brief", "and", "sprout"])
        self.assertEqual(names.words("0293-brief-and-sprout", True), ["brief", "and", "sprout"])
        self.assertEqual(names.words("2024-roadmap"), ["2024", "roadmap"])

    def test_research_does_not_count_but_researcher_does(self):
        self.assertEqual(names.words("0077-research-spec-seed", True), ["spec", "seed"])
        self.assertEqual(names.words("Research: plugin runtimes"), ["plugin", "runtimes"])
        self.assertEqual(names.words("researcher view"), ["researcher", "view"])

    def test_a_masterplans_marker_does_not_count(self):
        self.assertEqual(names.words("0274-masterplan-halverse-plugin", True), ["halverse", "plugin"])
        self.assertEqual(names.words("Masterplan one two three four"), ["one", "two", "three", "four"])
        self.assertEqual(names.words("the masterplan view"), ["the", "masterplan", "view"])

    def test_four_words_pass_five_fail(self):
        self.assertFalse(names.too_long("one two three four"))
        self.assertTrue(names.too_long("one two three four five"))
        self.assertFalse(names.too_long("0001-research-one-two-three-four", True))
        self.assertTrue(names.too_long("0001-research-one-two-three-four-five", True))

    def test_refuse_names_the_rule_and_the_count(self):
        names.refuse("a b c d")
        with self.assertRaises(names.NameTooLong) as caught:
            names.refuse("a very long name of a plan")
        self.assertIn("plan-names-are-short", str(caught.exception))
        self.assertIn("has 7", str(caught.exception))


class ProblemsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        self.long = "0002-this-name-has-way-too-many-words"

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, slug: str) -> Path:
        path = self.root / "plans" / slug / "plan.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Plan\n")
        return path

    def test_without_a_default_branch_only_the_current_plan_counts(self):
        path = self.plan(self.long)
        other = self.plan("0003-another-name-with-too-many-words")

        found = names.problems(self.root, [path, other], self.long, slug_of)

        self.assertEqual(len(found), 1)
        self.assertIn(self.long, found[0])

    def test_a_short_name_passes(self):
        self.assertEqual(names.problems(self.root, [self.plan("0001-short-name")], "0001-short-name", slug_of), [])

    def test_a_landed_long_name_passes_an_unlanded_one_fails(self):
        landed = self.plan(self.long)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "landed")
        bare = Path(self.tmp.name) / "origin.git"
        git(self.root, "init", "-q", "--bare", str(bare))
        git(self.root, "remote", "add", "origin", str(bare))
        git(self.root, "push", "-q", "origin", "main")
        fresh = self.plan("0004-a-fresh-name-with-too-many-words")

        found = names.problems(self.root, [landed, fresh], "", slug_of)

        self.assertEqual(len(found), 1)
        self.assertIn("0004-", found[0])


if __name__ == "__main__":
    unittest.main()
