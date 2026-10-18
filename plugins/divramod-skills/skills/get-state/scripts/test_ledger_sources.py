"""The ledger readers of the farmer page (hal2 plan 0369, D11, D12): fixture plan folders, the stored format's parser,
the CLI's answer through an injected reader, one read per plan (D14, D15), and the degrade-to-empty cases."""

import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from pathlib import Path
from unittest import mock

import ledger_sources as ls

QUESTIONS = """---
type: Questions
---

# Questions and answers

<!-- ## Q99 · 2026-01-01 · agent · open  (the format hint in a comment is no entry only when indented) -->

## Q1 · 2026-10-07 · agent · answered 2026-10-08

**Q:** Signing: a) unsigned for now (recommended, the default),
b) with a certificate now, c) decided at milestone 1?
**A:** "1a" (the user): unsigned.
**Decision:** D4

## Q2 · 2026-10-09 · user · open

**Q:** "How much does it cost?"

## Q3 · 2026-10-10 · agent · dropped 2026-10-11

**Q:** Gone?
"""

DECISIONS = """# Decisions of plan 1

## D1 · 2026-10-18 · agent · in-force

**D:** Fresh data comes from a loopback server.
**Why:** a file page cannot rerun the collector.

## D2 · 2026-10-18 · user · superseded

**D:** Columns are reordered by dragging
a header onto another.
**Words:** "add, that i want to drag"
**Why (filter, sort):** agent: the newest first.
**By:** D3

## D3 · 2026-10-19 · lead · ended 2026-10-20

**D:** Three.
"""


def field(root: Path, wt: str, plan: str | None = "0001-x", questions: str | None = None, decisions: str | None = None) -> dict:
    base = root / wt
    base.mkdir()
    if plan:
        folder = base / "plans" / plan
        folder.mkdir(parents=True)
        for name, text in (("questions.md", questions), ("decisions.md", decisions)):
            if text is not None:
                (folder / name).write_text(text, encoding="utf-8")
    return {"wt": wt, "path": str(base), "plan": plan or "", "is_main": False}


class Parse(unittest.TestCase):
    def test_questions_with_options_state_and_answer(self):
        q = {e["n"]: e for e in ls.parse_questions(QUESTIONS)}
        self.assertEqual(sorted(q), [1, 2, 3])
        self.assertEqual(q[1]["state"], "answered")
        self.assertEqual(q[1]["question"], "Signing:")
        self.assertEqual(q[1]["options"], ["unsigned for now (recommended, the default)", "with a certificate now",
                                           "decided at milestone 1?"])
        self.assertEqual(q[1]["answer"], '"1a" (the user): unsigned.')
        self.assertEqual((q[2]["state"], q[2]["options"], q[2]["answer"]), ("open", [], None))
        self.assertEqual((q[3]["state"], q[3]["date"]), ("dropped", "2026-10-10"))

    def test_split_options_needs_a_and_b(self):
        self.assertEqual(ls.split_options("Which? a) x, b) y"), ("Which?", ["x", "y"]))
        self.assertEqual(ls.split_options("Is it (a) fine?"), ("Is it (a) fine?", []))
        self.assertEqual(ls.split_options("No options here"), ("No options here", []))

    def test_garbage_gives_nothing(self):
        self.assertEqual(ls.parse_questions(""), [])
        self.assertEqual(ls.parse_questions("## Q? broken\n**Q:** x"), [])


class Decisions(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.root = Path(self._d.name)
        self.addCleanup(self._d.cleanup)

    def test_entries_fields_state_and_newest_first_per_field(self):
        rows = [field(self.root, "01", decisions=DECISIONS), field(self.root, "02", plan="0002-y", decisions="## D7 · 2026-01-02 · user · promoted\n\n**D:** Seven.\n")]
        got = ls.decisions(rows)
        self.assertEqual([(d["wt"], d["n"]) for d in got], [("01", "D3"), ("01", "D2"), ("01", "D1"), ("02", "D7")])
        by = {d["n"]: d for d in got}
        self.assertEqual((by["D1"]["plan"], by["D1"]["who"], by["D1"]["state"]), ("0001-x", "agent", "in-force"))
        self.assertEqual(by["D1"]["decision"], "Fresh data comes from a loopback server.")
        self.assertEqual(by["D1"]["why"], "a file page cannot rerun the collector.")
        self.assertEqual(by["D2"]["decision"], "Columns are reordered by dragging a header onto another.")
        self.assertEqual((by["D2"]["words"], by["D2"]["why"]), ('"add, that i want to drag"', ""))
        self.assertEqual((by["D3"]["state"], by["D3"]["date"]), ("ended", "2026-10-19"))
        self.assertEqual(by["D7"]["state"], "promoted")

    def test_only_numbered_fields_with_a_plan_folder_count(self):
        rows = [field(self.root, "03", plan=None), {**field(self.root, "04", decisions=DECISIONS), "wt": "farmer-x"},
                {**field(self.root, "05", decisions=DECISIONS), "is_main": True}, {"wt": "06"}, {"wt": "07", "plan": "x", "path": "/nonexistent"},
                field(self.root, "08", plan="0008-z")]
        self.assertEqual(ls.decisions(rows), [])
        self.assertEqual([q["wt"] for q in ls.questions(rows, read=lambda r: [{"n": 1}])], ["08"])

    def test_a_plan_path_names_its_folder_and_a_missing_file_is_empty(self):
        row = field(self.root, "01", plan="0001-x", decisions=DECISIONS)
        self.assertEqual(len(ls.decisions([{**row, "plan": "plans/0001-x/plan.md\n"}])), 3)
        self.assertEqual(ls.decisions([field(self.root, "02", plan="0002-q")]), [])

    def test_a_current_plan_outside_the_fields_plans_folder_is_no_plan(self):
        row = field(self.root, "01", plan="0001-x", decisions=DECISIONS)
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "decisions.md").write_text(DECISIONS, encoding="utf-8")
        for text in (str(outside), "../../outside", "0001-x/../../../outside", "plans/../../outside", "..\\..\\outside",
                     "C:\\outside", "\\\\host\\share", "-rf"):
            self.assertIsNone(ls.plan_folder({**row, "plan": text}), text)
            self.assertEqual(ls.decisions([{**row, "plan": text}]), [], text)
        self.assertEqual(ls.plan_folder(row), (Path(row["path"]) / "plans" / "0001-x", "0001-x"))


class Questions(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.root = Path(self._d.name)
        self.addCleanup(self._d.cleanup)

    def test_a_cli_answer_with_odd_numbers_sorts_without_raising(self):
        rows = [field(self.root, "02")]
        read = lambda r: [{"n": 2}, {"n": None}, {"n": "7"}, {"n": True}, {"n": 5}]  # noqa: E731
        self.assertEqual([q["n"] for q in ls.questions(rows, read=read)], ["Q5", "Q2", "QNone", "Q7", "QTrue"])

    def test_an_injected_reader_gives_rows_newest_first_with_field_and_plan(self):
        rows = [field(self.root, "02", questions=QUESTIONS), field(self.root, "01", plan="0001-w")]
        seen = []

        def read(row):
            seen.append(row["wt"])
            return [{"n": 1, "state": "open", "question": "A?"}, {"n": 2, "state": "answered", "question": "B?", "options": ["x"]}]
        got = ls.questions(rows, read=read)
        self.assertEqual(sorted(seen), ["01", "02"])
        self.assertEqual([(q["wt"], q["plan"], q["n"]) for q in got], [("02", "0001-x", "Q2"), ("02", "0001-x", "Q1"),
                                                                        ("01", "0001-w", "Q2"), ("01", "0001-w", "Q1")])
        self.assertEqual((got[0]["options"], got[1]["options"], got[1]["answer"]), (["x"], [], None))

    def test_a_failing_reader_costs_only_that_field(self):
        rows = [field(self.root, "01"), field(self.root, "02", plan="0002-y")]

        def read(row):
            if row["wt"] == "01":
                raise RuntimeError("boom")
            return [{"n": 1, "state": "open", "question": "ok"}]
        self.assertEqual([q["wt"] for q in ls.questions(rows, read=read)], ["02"])

    def test_the_cli_answer_is_used_when_it_works(self):
        row = field(self.root, "01", questions=QUESTIONS)
        out = '{"store": "x", "mode": "all", "entries": [{"n": 5, "state": "open", "question": "From CLI?", "options": ["a1"], "answer": null, "date": null, "extra": 1}]}'
        done = mock.Mock(returncode=0, stdout=out)
        with mock.patch.object(ls.subprocess, "run", return_value=done) as run:
            got = ls.questions([row])
        self.assertEqual([(q["n"], q["question"]) for q in got], [("Q5", "From CLI?")])
        self.assertEqual(run.call_args.args[0][:5], ["hal2-cli-plans", "questions", "list", "--all", "--json"])
        self.assertIn("0001-x", run.call_args.args[0])

    def test_without_the_cli_the_file_is_parsed(self):
        row = field(self.root, "01", questions=QUESTIONS)
        for failure in (FileNotFoundError(), mock.Mock(returncode=1, stdout=""), mock.Mock(returncode=0, stdout="not json")):
            with mock.patch.object(ls.subprocess, "run", **({"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure})):
                got = ls.questions([row])
            self.assertEqual([q["n"] for q in got], ["Q3", "Q2", "Q1"], failure)
            self.assertEqual(got[2]["options"][0], "unsigned for now (recommended, the default)")


class OnePerPlan(unittest.TestCase):
    """Plan 0369 D14: a plan's ledgers are read once, from the field that runs it, not from a servant's copy."""

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.root = Path(self._d.name)
        self.addCleanup(self._d.cleanup)
        self.rows = [{**field(self.root, "01", decisions=DECISIONS), "foreman": "05"},  # a servant's copy of 0001-x
                     field(self.root, "05", decisions=DECISIONS),                       # 0001-x's own field
                     {**field(self.root, "07", plan="0002-y", decisions=DECISIONS), "foreman": "09"},  # only servants
                     {**field(self.root, "08", plan="0002-y", decisions=DECISIONS), "foreman": "09"}]

    def test_sources_take_the_running_field_else_the_lowest_servant(self):
        self.assertEqual([r["wt"] for r in ls.sources(self.rows)], ["05", "07"])

    def test_each_plan_is_read_once(self):
        seen = []
        ls.questions(self.rows, read=lambda r: seen.append(r["wt"]) or [{"n": 1, "state": "open", "question": "?"}])
        self.assertEqual(sorted(seen), ["05", "07"])
        real, files = ls.read_text, []
        with mock.patch.object(ls, "read_text", side_effect=lambda f: files.append(f) or real(f)):
            got = ls.decisions(self.rows)
        self.assertEqual(len(files), 2)
        self.assertEqual(sorted({(d["wt"], d["plan"]) for d in got}), [("05", "0001-x"), ("07", "0002-y")])

    def test_the_cli_runs_once_per_plan_in_the_callers_pool(self):
        done = mock.Mock(returncode=0, stdout='{"entries": [{"n": 1, "state": "open", "question": "?"}]}')
        with mock.patch.object(ls.subprocess, "run", return_value=done) as run, ThreadPoolExecutor(2) as pool:
            got = ls.submit_questions(self.rows, pool)()
        self.assertEqual(sorted(c.args[0][-1] for c in run.call_args_list), ["0001-x", "0002-y"])
        self.assertEqual([(q["wt"], q["n"]) for q in got], [("05", "Q1"), ("07", "Q1")])


if __name__ == "__main__":
    unittest.main()
