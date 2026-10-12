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
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "skills" / "handoff").mkdir(parents=True)
        (self.root / "skills" / "handoff" / "SKILL.md").write_text("---\nname: handoff\n---\n")
        (self.root / ".claude-plugin").mkdir()
        (self.root / ".claude-plugin" / "plugin.json").write_text(MANIFEST)

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
        c = (self.root / "skills" / "c" / "SKILL.md").read_text()
        self.assertIn("name: c\n", c)
        self.assertIn("disable-model-invocation: true", c)
        self.assertIn("`/handoff continue`", c)
        self.assertIn("`/handoff`", (self.root / "skills" / "h" / "SKILL.md").read_text())
        self.assertEqual(self.manifest()["skills"], ["./skills/c", "./skills/h", "./skills/handoff"])
        self.assertIn('"keywords": ["a", "b"]', (self.root / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(self.run_gen(aliases, "--check"), 0)

    def test_removed_alias_deletes_its_stub(self):
        self.run_gen({"h": {"skill": "handoff"}})
        self.assertEqual(self.run_gen({}, "--check"), 1)
        self.assertEqual(self.run_gen({}), 0)
        self.assertFalse((self.root / "skills" / "h").exists())
        self.assertEqual(self.manifest()["skills"], ["./skills/handoff"])

    def test_unknown_target_and_clash_are_errors(self):
        self.assertEqual(self.run_gen({"x": {"skill": "nope"}}), 1)
        self.assertEqual(self.run_gen({"handoff": {"skill": "handoff"}}), 1)
        self.run_gen({"h": {"skill": "handoff"}})
        self.assertEqual(self.run_gen({"hh": {"skill": "h"}}), 1)  # no shortcut to a shortcut


if __name__ == "__main__":
    unittest.main()
