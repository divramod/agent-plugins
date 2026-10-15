import contextlib
import io
import json
import os
import sys
import unittest

import halverse
import ontology
import sources
from fake_cli import FakeCli


class Sources(FakeCli):
    def test_sections_split_title_and_status_and_keep_rows_and_bullets(self):
        secs = {s.title: s for s in sources.ontology_sections(sources.load())}
        self.assertEqual(secs["Places on the farm"].note, "in force, synonyms")
        self.assertEqual(secs["Places on the farm"].rows[0], {"farm word": "field", "stands for": "a worktree"})
        self.assertEqual(len(secs["Roles on the farm"].lines), 2)
        self.assertEqual(secs["Tools"].rows[0]["status"], "exists")

    def test_the_overview_gives_each_section_its_status_and_the_glossary_heads(self):
        data = ontology.overview(sources.load())
        acts = {s["title"]: s for s in data["sections"]}["Activities"]
        self.assertEqual({r["farm word"]: r["status"] for r in acts["rows"]}["bring in"], "in force (synonym)")
        self.assertEqual(data["glossary_terms"][0], ["shot", "seed"])

    def test_a_term_that_is_known_has_its_glossary_place_and_pair(self):
        data, known = ontology.lookup(sources.load(), "bring in")
        self.assertTrue(known)
        self.assertEqual(data["glossary"]["terms"], ["landing", "bring in"])
        self.assertEqual(data["pair"]["command"], "/mtm")


class Cli(FakeCli):
    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = halverse.main(["ontology", *args])
        return code, out.getvalue(), err.getvalue()

    def test_overview_json_has_statuses(self):
        code, out, _ = self.call("--json")
        self.assertEqual(code, 0)
        acts = {s["title"]: s for s in json.loads(out)["sections"]}["Activities"]
        self.assertEqual({r["farm word"]: r["status"] for r in acts["rows"]}["cockcrow"], "proposed, not chosen")

    def test_overview_text(self):
        code, out, _ = self.call()
        self.assertEqual(code, 0)
        self.assertIn("- cockcrow | the nightly start [proposed, not chosen]", out)

    def test_term_with_entry_place_old_word_and_command(self):
        code, out, _ = self.call("bring in")
        self.assertEqual(code, 0)
        self.assertIn("glossary (landing, bring in)", out)
        self.assertIn("ontology, Activities: bring in", out)
        self.assertIn("command: /mtm", out)

    def test_an_old_word_finds_its_pair(self):
        _, out, _ = self.call("mtm", "--json")
        self.assertEqual(json.loads(out)["pair"]["new"], "bring in")

    def test_unknown_term_names_the_closest_and_exits_1(self):
        code, _, err = self.call("sheed")
        self.assertEqual(code, 1)
        self.assertIn("closest: seed", err)

    def test_a_file_the_cli_cannot_read_is_named_and_exits_2(self):
        with open(self.path, "w") as handle:
            handle.write("#!%s\nimport sys\nprint(%r)\nsys.exit(2)\n" % (sys.executable, json.dumps(
                {"error": {"code": "unreadable", "message": "x", "detail": {"file": "dictation", "path": "/x/DICTATION.md"}}})))
        code, _, err = self.call()
        self.assertEqual(code, 2)
        self.assertIn("/x/DICTATION.md", err)

    def test_without_the_program_it_exits_2_and_names_the_install(self):
        os.remove(self.path)
        for args in ((), ("harvest",)):
            code, _, err = self.call(*args)
            self.assertEqual(code, 2)
            self.assertIn("cargo install --path apps/hal2-cli-halverse", err)

    def test_the_program_is_asked_for_terms_and_the_ontology_only(self):
        self.call("harvest")
        self.assertEqual(self.args(), ["terms --json", "ontology --json"])


if __name__ == "__main__":
    unittest.main()
