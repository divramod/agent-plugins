#!/usr/bin/env python3
"""Unit tests for check-plugins.py: the per-folder prerequisite rule and the layout rules, flat and category (offline)."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("check_plugins", Path(__file__).resolve().parent / "check-plugins.py")
check_plugins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_plugins)
prereq_errors = check_plugins.prereq_errors


class TestPrereqRule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skill = Path(self.tmp.name) / "skills" / "demo"
        (self.skill / "scripts").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, text: str = "", exe: bool = False) -> None:
        f = self.skill / "scripts" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        if exe:
            f.chmod(0o755)

    def prereqs(self, folder: str = "") -> None:
        for name in check_plugins.PREREQ_SCRIPTS:
            self.write(f"{folder}/{name}".lstrip("/"), "#!/bin/sh\n", exe=True)

    def test_no_tools_no_requirement(self):
        self.write("web/prepare.py", "import urllib.request\n")
        self.write("web/test_prepare.py", "import subprocess\n")  # tests don't count
        self.assertEqual(prereq_errors(self.skill), [])

    def test_source_folder_with_subprocess_needs_its_own_scripts(self):
        self.prereqs()
        self.write("video/prepare.py", "import subprocess\n")
        errors = prereq_errors(self.skill)
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("video" in e and "missing" in e for e in errors), errors)
        self.prereqs("video")
        self.assertEqual(prereq_errors(self.skill), [])

    def test_source_folder_needs_the_top_level_aggregators(self):
        self.write("video/prepare.py", "import subprocess\n")
        self.prereqs("video")
        errors = prereq_errors(self.skill)
        self.assertEqual([e.split(" ")[0] for e in errors],
                         ["skills/demo/scripts/check-prerequisites.sh", "skills/demo/scripts/install-prerequisites.sh"])

    def test_flat_scripts_folder_still_works(self):
        self.write("run.py", "import shutil\nshutil.which('jq')\n")
        self.assertEqual(len(prereq_errors(self.skill)), 2)
        self.prereqs()
        self.assertEqual(prereq_errors(self.skill), [])

    def test_not_executable(self):
        self.write("x/fetch.sh", "command -v curl\n")
        self.prereqs()
        self.prereqs("x")
        (self.skill / "scripts" / "x" / "install-prerequisites.sh").chmod(0o644)
        self.assertEqual(prereq_errors(self.skill), ["skills/demo/scripts/x/install-prerequisites.sh is not executable"])


CATEGORY = {"alpha": "actions", "beta": "roles", "c": "shortcuts"}


class LayoutBase(unittest.TestCase):
    """A fixture unit with skills alpha, beta and the shortcut c, flat or in categories (CATEGORIES)."""
    CATEGORIES = False

    def rel(self, name: str) -> str:
        return f"skills/{CATEGORY[name]}/{name}" if self.CATEGORIES else f"skills/{name}"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ("alpha", "beta"):
            self.skill(name)
        manifest = {"name": "demo", "version": "1.0.0"}
        (self.root / ".claude-plugin").mkdir()
        (self.root / ".codex-plugin").mkdir()
        (self.root / ".codex-plugin" / "plugin.json").write_text(json.dumps({**manifest, "skills": "./skills/"}))
        self.write_listing("alpha", "beta")

    def skill(self, name: str, text: str = "") -> Path:
        folder = self.root / self.rel(name)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n{text}")
        return folder

    def write_listing(self, *names: str) -> None:
        listing = [f"./{self.rel(n)}" for n in names]
        (self.root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "demo", "version": "1.0.0", "skills": listing}))

    def errors(self) -> list[str]:
        """The errors but the alias check's, which repeats a wrong listing (its own tests: test_gen_aliases.py)."""
        return [e for e in check_plugins.check(self.root)[0] if not e.startswith("shortcut skills are out of date")]


class TestLayoutFlat(LayoutBase):
    def test_a_clean_unit_has_no_errors(self):
        self.assertEqual(self.errors(), [])

    def test_a_skill_missing_from_the_listing_and_a_listed_ghost(self):
        self.skill("c")
        self.write_listing("alpha", "beta", "c")
        self.write_listing("alpha", "beta")
        self.assertEqual(self.errors(), [f"./{self.rel('c')} is missing from .claude-plugin/plugin.json skills"])
        self.write_listing("alpha", "beta", "c")
        (self.root / self.rel("c") / "SKILL.md").unlink()
        self.assertEqual(self.errors(), [f"./{self.rel('c')} is listed in .claude-plugin/plugin.json but has no SKILL.md"])

    def test_frontmatter_name_must_equal_the_folder(self):
        (self.root / self.rel("alpha") / "SKILL.md").write_text("---\nname: other\ndescription: d\n---\n")
        self.assertEqual(self.errors(), [f"{self.rel('alpha')}/SKILL.md: frontmatter name must be 'alpha'"])

    def test_a_sibling_link_resolves_beside_or_in_another_category(self):
        self.skill("alpha", "see [beta](../beta/SKILL.md#x)\n")
        deep = self.root / self.rel("alpha") / "instructions"
        deep.mkdir()
        (deep / "a.md").write_text("[beta](../../beta/SKILL.md) and [own](../SKILL.md)\n")
        self.assertEqual(self.errors(), [])

    def test_a_sibling_link_to_no_skill_is_an_error_naming_file_and_link(self):
        self.skill("alpha", "see [gone](../gone/SKILL.md)\n")
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn(f"{self.rel('alpha')}/SKILL.md", errors[0])
        self.assertIn("'gone'", errors[0])

    def test_prereq_errors_name_the_path_from_the_unit_root(self):
        folder = self.root / self.rel("alpha") / "scripts"
        folder.mkdir()
        (folder / "run.py").write_text("import subprocess\n")
        errors = self.errors()
        self.assertEqual(len(errors), 2)
        self.assertTrue(all(e.startswith(f"{self.rel('alpha')}/scripts/") for e in errors), errors)


class TestLayoutCategories(TestLayoutFlat):
    CATEGORIES = True

    def test_the_same_name_in_two_categories_is_an_error(self):
        twin = self.root / "skills" / "shortcuts" / "alpha"
        twin.mkdir(parents=True)
        (twin / "SKILL.md").write_text("---\nname: alpha\ndescription: d\n---\n")
        errors = self.errors()
        self.assertTrue(any("'alpha'" in e and "actions" in e and "shortcuts" in e for e in errors), errors)

    def test_a_flat_listing_of_a_categorised_skill_is_an_error(self):
        (self.root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "demo", "version": "1.0.0", "skills": ["./skills/alpha", "./skills/beta"]}))
        errors = self.errors()
        self.assertEqual(len(errors), 4, errors)  # two missing real paths, two ghosts


if __name__ == "__main__":
    unittest.main()
