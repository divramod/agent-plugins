import os
import tempfile
import unittest

import sources

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "fixtures", "sources")


class FarmWords(unittest.TestCase):
    def setUp(self):
        self.words = sources.farm_words(sources.read_text(os.path.join(SAMPLE, "ontology.md")))
        self.by_word = {w.word: w for w in self.words}

    def test_places_and_activities_tables_are_read_other_tables_are_not(self):
        self.assertEqual(sorted(self.by_word),
                         ["cockcrow", "continue", "field", "hand off", "harvest", "jot", "pause", "tick off", "yard"])

    def test_a_table_without_status_is_in_force(self):
        self.assertTrue(self.by_word["field"].in_force)
        self.assertEqual(self.by_word["field"].section, "Places on the farm (in force, synonyms)")

    def test_status_decides_in_force(self):
        self.assertTrue(self.by_word["harvest"].in_force)
        self.assertTrue(self.by_word["pause"].in_force)
        self.assertFalse(self.by_word["cockcrow"].in_force)

    def test_a_cell_with_two_words_is_split_and_backticks_go(self):
        self.assertEqual(self.by_word["jot"].stands_for, self.by_word["tick off"].stands_for)
        self.assertEqual(self.by_word["harvest"].stands_for, "merge-to-main (`/mtm`)")

    def test_missing_or_empty_text(self):
        self.assertEqual(sources.farm_words(None), [])
        self.assertEqual(sources.farm_words(""), [])


class Glossary(unittest.TestCase):
    def test_headings_with_two_terms_are_pairs(self):
        text = sources.read_text(os.path.join(SAMPLE, "GLOSSARY.md"))
        self.assertEqual(sources.glossary_pairs(text), [("shot", "seed"), ("landing", "harvest")])

    def test_three_terms_pair_the_first_with_each_other(self):
        self.assertEqual(sources.glossary_pairs("**a**, **b**, **c**:\ntext **x**, **y**\n"), [("a", "b"), ("a", "c")])

    def test_none(self):
        self.assertEqual(sources.glossary_pairs(None), [])


class Paths(unittest.TestCase):
    def test_env_overrides_and_missing_file_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {k: os.environ.get(k) for k in (sources.GLOSSARY_ENV, sources.ONTOLOGY_ENV)}
            try:
                os.environ[sources.GLOSSARY_ENV] = os.path.join(tmp, "g.md")
                os.environ[sources.ONTOLOGY_ENV] = os.path.join(tmp, "o.md")
                self.assertEqual(sources.glossary_path(), os.path.join(tmp, "g.md"))
                self.assertEqual(sources.ontology_path(), os.path.join(tmp, "o.md"))
                self.assertIsNone(sources.read_text(sources.glossary_path()))
            finally:
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
