#!/usr/bin/env python3
"""Unit tests for gen-aliases.py (offline, on a temporary repo)."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("gen_aliases", Path(__file__).resolve().parent / "gen-aliases.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

MANIFEST = '{\n  "name": "demo",\n  "keywords": ["a", "b"],\n  "skills": [\n    "./skills/handoff"\n  ]\n}\n'


class TestGenAliases(unittest.TestCase):
    CATEGORIES = False  # True: skills/<category>/<name>/ with the stubs in skills/shortcuts/

    @property
    def sk(self) -> Path:
        """Where skills and stubs live: skills/ (flat) or skills/shortcuts/ for the stubs."""
        return self.root / "skills"

    def stub_path(self, alias: str) -> Path:
        return self.sk / ("shortcuts" if self.CATEGORIES else "") / alias / "SKILL.md"

    def listed(self, *names: str) -> list[str]:
        return [f"./skills/{n}" for n in names]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        home = self.sk / ("actions" if self.CATEGORIES else "") / "handoff"
        home.mkdir(parents=True)
        (home / "SKILL.md").write_text("---\nname: handoff\n---\n")
        (self.root / ".claude-plugin").mkdir()
        manifest = MANIFEST.replace("./skills/handoff", "./skills/actions/handoff" if self.CATEGORIES else "./skills/handoff")
        (self.root / ".claude-plugin" / "plugin.json").write_text(manifest)

    def tearDown(self):
        self.tmp.cleanup()

    def run_gen(self, aliases: dict, *argv: str) -> int:
        (self.root / "aliases.json").write_text(json.dumps(aliases))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return gen.main(list(argv), root=self.root)

    def manifest(self) -> dict:
        return json.loads((self.root / ".claude-plugin" / "plugin.json").read_text())

    def test_generates_stubs_and_lists_them(self):
        aliases = {"h": {"skill": "handoff"}, "c": {"skill": "handoff", "args": "continue"}}
        self.assertEqual(self.run_gen(aliases, "--check"), 1)
        self.assertEqual(self.run_gen(aliases), 0)
        c = self.stub_path("c").read_text()
        self.assertIn("name: c\n", c)
        self.assertIn("disable-model-invocation: true", c)
        self.assertIn("`/handoff continue`", c)
        self.assertIn("`/handoff`", self.stub_path("h").read_text())
        self.assertIn("(../handoff/SKILL.md)", c)  # the flat installed form (D19)
        if self.CATEGORIES:
            self.assertEqual(self.manifest()["skills"], self.listed("actions/handoff", "shortcuts/c", "shortcuts/h"))
        else:
            self.assertEqual(self.manifest()["skills"], self.listed("c", "h", "handoff"))
        self.assertIn('"keywords": ["a", "b"]', (self.root / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(self.run_gen(aliases, "--check"), 0)

    def test_removed_alias_deletes_its_stub(self):
        self.run_gen({"h": {"skill": "handoff"}})
        self.assertEqual(self.run_gen({}, "--check"), 1)
        self.assertEqual(self.run_gen({}), 0)
        self.assertFalse(self.stub_path("h").parent.exists())
        self.assertEqual(self.manifest()["skills"], self.listed("actions/handoff" if self.CATEGORIES else "handoff"))

    def test_unknown_target_and_clash_are_errors(self):
        self.assertEqual(self.run_gen({"x": {"skill": "nope"}}), 1)
        self.assertEqual(self.run_gen({"handoff": {"skill": "handoff"}}), 1)
        self.run_gen({"h": {"skill": "handoff"}})
        self.assertEqual(self.run_gen({"hh": {"skill": "h"}}), 1)  # no shortcut to a shortcut

    def test_a_stub_in_the_wrong_place_moves_and_a_real_skill_blocks_its_alias(self):
        self.run_gen({"h": {"skill": "handoff"}})
        other = self.root / "skills" / ("actions" if self.CATEGORIES else "") / "real" / "SKILL.md"
        other.parent.mkdir(parents=True)
        other.write_text("---\nname: real\n---\n")
        self.assertEqual(self.run_gen({"real": {"skill": "handoff"}}), 1)  # clash with the real skill
        self.assertEqual(self.run_gen({"h": {"skill": "real"}}), 0)
        self.assertIn("../real/SKILL.md", self.stub_path("h").read_text())


class TestGenAliasesCategories(TestGenAliases):
    CATEGORIES = True

    def test_a_flat_stub_left_over_is_replaced_by_one_in_shortcuts(self):
        flat = self.root / "skills" / "h" / "SKILL.md"
        flat.parent.mkdir()
        flat.write_text(gen.stub("h", "handoff", ""))
        self.assertEqual(self.run_gen({"h": {"skill": "handoff"}}), 0)
        self.assertFalse(flat.parent.exists())
        self.assertTrue(self.stub_path("h").is_file())


class TestShippedAliases(unittest.TestCase):
    """The real aliases.json: mfm and mtm reach the long-named skills and pass their arguments on (D54)."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_mfm_and_mtm_hand_over_to_the_long_names_with_their_arguments(self):
        aliases = gen.load_aliases(self.ROOT)
        for alias, skill in (("mfm", "merge-from-main"), ("mtm", "merge-to-main"), ("q", "get-open-questions"),
                             ("s", "get-state")):
            self.assertEqual(aliases[alias], {"skill": skill, "args": ""})
            self.assertIsNotNone(gen.find_skill(self.ROOT, skill), skill)
            stub = gen.stub(alias, skill, "")
            self.assertIn(f"`/{alias} <args>` runs `/{skill} <args>`", stub)  # `/mtm milestone`, `/mtm h`
            self.assertIn(f"with any arguments given to `/{alias}` appended", stub)
            self.assertEqual(gen.wanted_files(self.ROOT)[self.ROOT / "skills" / "shortcuts" / alias / "SKILL.md"], stub)

    def test_q_a_reaches_get_open_questions_as_a(self):
        stub = gen.stub("q", "get-open-questions", "")
        self.assertIn("`/q <args>` runs `/get-open-questions <args>`", stub)  # `/q a`, `/q l`


if __name__ == "__main__":
    unittest.main()
