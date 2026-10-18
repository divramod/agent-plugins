"""The farmer page's Questions and Decisions tables (hal2 plan 0369, D11, D12) over hand-made ledger rows and over a
fixture plan folder; the readers themselves are in test_ledger_sources."""

import unittest
from pathlib import Path

import grid
import view_farmer as vf
from test_view_farmer import col, data, row, tables


QUESTIONS = [
    {"wt": "02", "plan": "0002-x", "n": "Q2", "state": "answered", "question": "Which?", "options": ["one", "two", "three"],
     "answer": "\"1a\" (the user)"},
    {"wt": "02", "plan": "0002-x", "n": "Q1", "state": "open", "question": "Why?", "options": [], "answer": None},
    {"wt": "05", "plan": "0005-y", "n": "Q3", "state": "dropped", "question": "Gone?"},
]
DECISIONS = [
    {"wt": "02", "plan": "0002-x", "n": "D1", "date": "2026-10-17", "who": "agent", "state": "in-force", "decision": "Old.",
     "words": "", "why": "Because."},
    {"wt": "05", "plan": "0005-y", "n": "D2", "date": "2026-10-18", "who": "user", "state": "superseded", "decision": "Newer.",
     "words": "\"yes\"", "why": ""},
    {"wt": "05", "plan": "0005-y", "n": "D3", "date": "2026-10-19", "who": "user", "state": "promoted", "decision": "Newest.",
     "words": "", "why": ""},
]


class LedgerTables(unittest.TestCase):
    def t(self, key: str, items: list):
        return vf.table({**data(), key: items}, key)

    def test_questions_columns_filters_and_the_open_default(self):
        t = self.t("questions", QUESTIONS)
        self.assertEqual([c["label"] for c in t["columns"]], ["Field", "Plan", "Q", "Question", "Options", "Answer", "State"])
        self.assertEqual([f["label"] for f in t["filters"]], ["Open", "Answered", "All"])
        self.assertEqual(grid.default_filter(t), "open")
        self.assertEqual(col(t, "n"), ["Q2", "Q1", "Q3"])
        self.assertEqual([r["n"] for r in grid.view(t)[1]], ["Q1"])
        by = {f["key"]: [r["n"] for r in t["rows"] if grid.matches(r, f)] for f in t["filters"]}
        self.assertEqual(by, {"open": ["Q1"], "answered": ["Q2"], "all": ["Q2", "Q1", "Q3"]})

    def test_question_options_are_one_lettered_cell_and_texts_stay_whole(self):
        r = self.t("questions", QUESTIONS)["rows"][0]
        self.assertEqual((r["options"], r["answer"]), ("a) one; b) two; c) three", "\"1a\" (the user)"))
        self.assertEqual(self.t("questions", QUESTIONS)["rows"][1]["options"], "")
        long = "word " * 80
        self.assertEqual(self.t("questions", [{**QUESTIONS[1], "question": long}])["rows"][0]["question"], long)

    def test_decisions_columns_hidden_words_and_why_and_the_in_force_default(self):
        t = self.t("decisions", DECISIONS)
        self.assertEqual([c["label"] for c in t["columns"]],
                         ["Field", "Plan", "D", "Date", "Who", "State", "Decision", "Words", "Why"])
        self.assertEqual([c["key"] for c in t["columns"] if c.get("hidden")], ["words", "why"])
        self.assertEqual([f["label"] for f in t["filters"]], ["In force", "All"])
        self.assertEqual(t["sort"], {"key": "date", "dir": "desc"})
        self.assertEqual([r["n"] for r in grid.view(t)[1]], ["D3", "D1"])  # promoted stays in force
        t["filter"] = "all"
        self.assertEqual([r["n"] for r in grid.view(t)[1]], ["D3", "D2", "D1"])

    def test_empty_ledgers_show_their_text(self):
        self.assertEqual(self.t("questions", [])["empty"], "No questions.")
        self.assertEqual(self.t("decisions", [])["empty"], "No decisions.")

    def test_without_data_keys_the_view_reads_the_fields_plan_folders(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "plans/0001-x"
            f.mkdir(parents=True)
            (f / "decisions.md").write_text("## D1 · 2026-10-18 · agent · in-force\n\n**D:** Yes.\n")
            (f / "questions.md").write_text("## Q1 · 2026-10-18 · agent · open\n\n**Q:** Really?\n")
            t = tables(row("01", 1, 2, plan="0001-x", path=d))
        self.assertEqual(col(t["decisions"], "decision"), ["Yes."])
        self.assertEqual(col(t["questions"], "question"), ["Really?"])
        self.assertEqual(tables(row("01", 1, 2))["decisions"]["rows"], [])


if __name__ == "__main__":
    unittest.main()
