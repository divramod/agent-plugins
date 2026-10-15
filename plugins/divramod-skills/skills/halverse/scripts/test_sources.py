import unittest

import sources
from fake_cli import FakeCli


def term(name, synonyms=(), definition="", glossary=True):
    return {"term": name, "synonyms": list(synonyms), "definition": definition,
            "glossary": {"section": "S", "line": 1} if glossary else None}


def table(header, *rows):
    return {"header": header, "rows": [{"cells": list(r), "line": 1} for r in rows]}


class OnFake(FakeCli):
    """The sample files as the CLI read them (fixtures/cli/sources), through load()."""

    def setUp(self):
        super().setUp()
        self.data = sources.load()


class FarmWords(OnFake):
    def setUp(self):
        super().setUp()
        self.words = sources.farm_words(self.data)
        self.by_word = {w.word: w for w in self.words}

    def test_load_runs_terms_and_ontology(self):
        self.assertEqual(self.args(), ["terms --json", "ontology --json"])

    def test_places_and_activities_tables_are_read_other_tables_are_not(self):
        self.assertEqual(sorted(self.by_word),
                         ["bring in", "cockcrow", "continue", "field", "hand off", "harvest", "jot", "pause", "tick off", "yard"])

    def test_a_table_without_status_is_in_force(self):
        self.assertTrue(self.by_word["field"].in_force)
        self.assertEqual(self.by_word["field"].section, "Places on the farm (in force, synonyms)")

    def test_status_decides_in_force(self):
        self.assertTrue(self.by_word["harvest"].in_force)
        self.assertTrue(self.by_word["pause"].in_force)
        self.assertFalse(self.by_word["cockcrow"].in_force)

    def test_a_cell_with_two_words_is_split_and_backticks_go(self):
        self.assertEqual(self.by_word["jot"].stands_for, self.by_word["tick off"].stands_for)
        self.assertEqual(self.by_word["bring in"].stands_for, "merge-to-main (`/mtm`)")

    def test_no_ontology(self):
        self.assertEqual(sources.farm_words(sources.Loaded({}, {})), [])
        self.assertEqual(sources.farm_words(sources.Loaded({}, {"sections": [{"title": "T", "tables": []}]})), [])


class Glossary(OnFake):
    def test_entries_with_two_heads_are_pairs(self):
        self.assertEqual(sources.glossary_pairs(self.data), [("shot", "seed"), ("landing", "bring in")])

    def test_three_heads_pair_the_first_with_each_other(self):
        data = sources.Loaded({"terms": [term("a", ["b", "c"]), term("x"), term("y", ["z"], glossary=False)]}, {})
        self.assertEqual(sources.glossary_pairs(data), [("a", "b"), ("a", "c")])

    def test_empty(self):
        self.assertEqual(sources.glossary_pairs(sources.Loaded({}, {})), [])

    def test_an_entry_is_its_heads_and_its_definition_only(self):
        entries = sources.glossary_entries(self.data)
        self.assertEqual([e.terms for e in entries][:2], [["shot", "seed"], ["landing", "bring in"]])
        self.assertEqual(entries[0].text, "One prompt in a shotfile.")
        self.assertEqual(len(entries), 5)  # the ontology's terms without an entry are none

    def test_an_avoid_line_is_not_in_the_text(self):
        data = sources.Loaded({"terms": [term("a", definition="What it is.")]}, {})
        self.assertEqual(sources.glossary_entries(data)[0].text, "What it is.")


class Lookups(OnFake):
    def test_entry_by_either_head_and_quoted(self):
        self.assertEqual(sources.glossary_entry(self.data, "seed").terms, ["shot", "seed"])
        self.assertEqual(sources.glossary_entry(self.data, "tell the farm").text, "A message to every agent.")
        self.assertEqual(sources.glossary_entry(self.data, '"Tell The Farm"').terms, ["tell the farm"])
        self.assertIsNone(sources.glossary_entry(self.data, "nothing"))

    def test_mentions_are_whole_words(self):
        self.assertEqual([s for s, _ in sources.ontology_mentions(self.data, "harvest")], ["Activities"])
        self.assertEqual(sources.ontology_mentions(self.data, "har"), [])

    def test_all_terms_are_the_glossarys_the_ontologys_and_the_farm_words(self):
        terms = sources.all_terms(self.data)
        for word in ("seed", "shot", "bring in", "tick off", "steward", "yard"):
            self.assertIn(word, terms)
        self.assertEqual(terms, sorted(set(terms)))


class Sections(OnFake):
    def test_sections_split_title_and_note_and_keep_rows_and_bullets(self):
        secs = {s.title: s for s in sources.ontology_sections(self.data)}
        self.assertEqual(secs["Places on the farm"].note, "in force, synonyms")
        self.assertEqual(secs["Places on the farm"].rows[0], {"farm word": "field", "stands for": "a worktree"})
        self.assertEqual(len(secs["Roles on the farm"].lines), 2)
        self.assertEqual(secs["Roles on the farm"].lines[0], "- **steward**: the session in the main checkout, with the user.")
        self.assertEqual(secs["Tools"].rows[0]["status"], "exists")

    def test_the_rows_of_two_tables_of_a_section_are_joined(self):
        ontology = {"sections": [{"title": "T", "note": "", "tables": [table(["a", "b"], ["1", "2"]), table(["c"], ["3"])],
                                  "lines": [{"text": "prose"}]}]}
        sec = sources.ontology_sections(sources.Loaded({}, ontology))[0]
        self.assertEqual(sec.rows, [{"a": "1", "b": "2"}, {"c": "3"}])
        self.assertEqual(sec.lines, ["prose"])


if __name__ == "__main__":
    unittest.main()
