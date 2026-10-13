import contextlib
import io
import json
import os
import unittest

import halverse
import ontology
import sources

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "fixtures", "sources")
GLOSSARY = sources.read_text(os.path.join(SAMPLE, "GLOSSARY.md"))
ONTOLOGY = sources.read_text(os.path.join(SAMPLE, "ontology.md"))


class Sources(unittest.TestCase):
    def test_sections_split_title_and_status_and_keep_rows_and_bullets(self):
        secs = {s.title: s for s in sources.ontology_sections(ONTOLOGY)}
        self.assertEqual(secs["Places on the farm"].note, "in force, synonyms")
        self.assertEqual(secs["Places on the farm"].rows[0], {"farm word": "field", "stands for": "a worktree"})
        self.assertEqual(len(secs["Roles on the farm"].lines), 2)
        self.assertEqual(secs["Tools"].rows[0]["status"], "exists")

    def test_glossary_entry_by_either_term_and_quoted(self):
        self.assertEqual(sources.glossary_entry(GLOSSARY, "seed").terms, ["shot", "seed"])
        self.assertEqual(sources.glossary_entry(GLOSSARY, "tell the farm").text, "A message to every agent.")
        self.assertIsNone(sources.glossary_entry(GLOSSARY, "nothing"))

    def test_mentions_are_whole_words(self):
        self.assertEqual([s for s, _ in sources.ontology_mentions(ONTOLOGY, "harvest")], ["Activities"])
        self.assertEqual(sources.ontology_mentions(ONTOLOGY, "har"), [])


class Cli(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("HALVERSE_GLOSSARY", "HALVERSE_ONTOLOGY")}
        os.environ["HALVERSE_GLOSSARY"] = os.path.join(SAMPLE, "GLOSSARY.md")
        os.environ["HALVERSE_ONTOLOGY"] = os.path.join(SAMPLE, "ontology.md")

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

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

    def test_missing_file_is_named_and_exits_2(self):
        os.environ["HALVERSE_ONTOLOGY"] = os.path.join(SAMPLE, "none.md")
        code, _, err = self.call()
        self.assertEqual(code, 2)
        self.assertIn("none.md", err)


if __name__ == "__main__":
    unittest.main()
