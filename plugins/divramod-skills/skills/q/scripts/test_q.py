"""q.py finds the session's question store and prints its entries in the Q form."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "q.py"
STORE = """---
type: Questions
---

# Questions and answers

<!-- ## Q9 · 2026-01-01 · agent · open  (the head comment shows the format; it is no entry) -->

## Q1 · 2026-10-07 · agent · answered 2026-10-08

**Q:** Windows code signing?
  a) (Recommended) unsigned for now — fast
  b) a certificate — costs money
  c) later — nothing now
**A:** "unsigned for now"
**Decision:** D1

## Q2 · 2026-10-09 · user · open

**Q:** "Tell me if the install worked"

## Q3 · 2026-10-09 · agent · open

**Q:** Which one?
  a) (Recommended) this — x
  b) that — y
  c) none — z

## Q4 · 2026-10-09 · agent · dropped 2026-10-10

**Q:** May it land itself?
**A:** no longer needed
"""


class Q(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / ".git").mkdir()
        (self.root / "plans" / "0003-x").mkdir(parents=True)
        (self.root / "plans" / "0003-x" / "plan.md").write_text("# Plan 0003: x\n")

    def tearDown(self):
        self.tmp.cleanup()

    def q(self, *args, cwd=None):
        return subprocess.run(["python3", str(SCRIPT), *args], cwd=cwd or self.root, text=True, capture_output=True)

    def plan_store(self, text=STORE):
        (self.root / "plans" / "CURRENT_PLAN").write_text("0003-x\n")
        (self.root / "plans" / "0003-x" / "questions.md").write_text(text)

    def test_the_store_is_the_current_plans_questions(self):
        self.plan_store()
        self.assertEqual(self.q("--path").stdout.strip(), "plans/0003-x/questions.md")

    def test_current_plan_may_hold_a_path(self):
        (self.root / "plans" / "CURRENT_PLAN").write_text("plans/0003-x/\n")
        self.assertEqual(self.q("--path").stdout.strip(), "plans/0003-x/questions.md")

    def test_the_store_is_the_plan_the_handoff_links_when_current_plan_names_a_task(self):
        (self.root / "plans" / "CURRENT_PLAN").write_text("fix-login\n")
        (self.root / "HANDOFF.md").write_text("[x](plans/0003-x/plan.md): 1/2\n")
        self.assertEqual(self.q("--path").stdout.strip(), "plans/0003-x/questions.md")

    def test_without_a_plan_the_store_is_the_root_questions_file(self):
        (self.root / "plans" / "CURRENT_PLAN").write_text("fix-login\n")
        self.assertEqual(self.q("--path").stdout.strip(), "QUESTIONS.md")
        (self.root / "QUESTIONS.md").write_text(STORE)
        self.assertIn("2 open questions (QUESTIONS.md)", self.q().stdout)

    def test_open_prints_the_entries_as_they_stand_in_the_q_form(self):
        self.plan_store()
        out = self.q()
        self.assertEqual(out.returncode, 0)
        self.assertEqual(out.stdout, "2 open questions (plans/0003-x/questions.md)\n\n"
                         'Q2: "Tell me if the install worked"\n\n'
                         "Q3: Which one?\n  a) (Recommended) this — x\n  b) that — y\n  c) none — z\n")

    def test_answered_follows_each_entry_with_its_answer(self):
        self.plan_store()
        out = self.q("a").stdout
        self.assertEqual(out, "1 answered question (plans/0003-x/questions.md)\n\n"
                         "Q1: Windows code signing?\n  a) (Recommended) unsigned for now — fast\n"
                         "  b) a certificate — costs money\n  c) later — nothing now\n"
                         'Answer (2026-10-08): "unsigned for now"\n')
        self.assertEqual(self.q("answered").stdout, out)

    def test_list_has_the_open_first_then_the_answered_and_dropped_by_number(self):
        self.plan_store()
        out = self.q("l").stdout
        self.assertTrue(out.startswith("4 questions, 2 open (plans/0003-x/questions.md)\n"))
        order = [ln.split(":")[0] for ln in out.splitlines() if ln.startswith("Q")]
        self.assertEqual(order, ["Q2", "Q3", "Q1", "Q4"])
        self.assertIn("Dropped (2026-10-10): no longer needed", out)
        self.assertEqual(self.q("list").stdout, out)

    def test_an_entry_without_options_gets_none_invented(self):
        self.plan_store()
        self.assertNotIn(" a) ", self.q().stdout.split("Q3")[0])

    def test_no_store_or_no_entries_is_one_line_and_exit_0(self):
        for mode, line in (("", "no open questions"), ("a", "no answered questions"), ("l", "no questions")):
            out = self.q(*([mode] if mode else []))
            self.assertEqual((out.returncode, out.stdout), (0, line + "\n"))
        self.plan_store(STORE.split("## Q1")[0])
        self.assertEqual(self.q().stdout, "no open questions\n")

    def test_only_answered_entries_print_no_open_questions(self):
        self.plan_store("## Q1 · 2026-10-07 · agent · answered 2026-10-08\n\n**Q:** x?\n**A:** y\n")
        self.assertEqual(self.q().stdout, "no open questions\n")

    def test_json_has_the_same_entries(self):
        self.plan_store()
        data = json.loads(self.q("l", "--json").stdout)
        self.assertEqual(data["store"], "plans/0003-x/questions.md")
        self.assertEqual([e["n"] for e in data["entries"]], [2, 3, 1, 4])
        self.assertEqual(data["entries"][1]["question"], "Which one?\n  a) (Recommended) this — x\n"
                         "  b) that — y\n  c) none — z")
        self.assertEqual(data["entries"][2]["closed"], "2026-10-08")
        self.assertEqual([e["n"] for e in json.loads(self.q("--json").stdout)["entries"]], [2, 3])

    def test_a_broken_store_is_one_line_naming_the_file_and_exit_1(self):
        self.plan_store("## Q1 - today - open\n\n**Q:** x?\n")
        out = self.q()
        self.assertEqual(out.returncode, 1)
        self.assertEqual(len(out.stdout.splitlines()), 1)
        self.assertTrue(out.stdout.startswith("plans/0003-x/questions.md: heading does not match"))
        self.assertNotIn("Traceback", out.stderr)

    def test_a_duplicate_number_is_a_broken_store(self):
        self.plan_store(STORE + "\n## Q2 · 2026-10-09 · user · open\n\n**Q:** again?\n")
        out = self.q()
        self.assertEqual(out.returncode, 1)
        self.assertIn("Q2: the number is used twice", out.stdout)

    def test_repo_names_another_checkout_and_a_subfolder_finds_its_own(self):
        self.plan_store()
        other = Path(tempfile.mkdtemp())
        try:
            self.assertEqual(self.q("--path", "--repo", str(self.root), cwd=other).stdout.strip(),
                             "plans/0003-x/questions.md")
            self.assertEqual(self.q("--path", cwd=self.root / "plans").stdout.strip(), "plans/0003-x/questions.md")
        finally:
            other.rmdir()


class FarmerSlot(unittest.TestCase):
    """In the farmer's own slot `farmer-<repo>` /q is the farmer's joined list (plan 0268, D14)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.state = base / "state"
        (self.state / "farmer-x").mkdir(parents=True)
        (self.state / "farmer-x" / "questions.jsonl").write_text(json.dumps(
            {"schema": 1, "at": "2026-10-13T10:00:00Z", "n": 1, "slot": "05", "text": "Q1: Land it?", "waits": "the landing",
             "state": "open", "asked": "2026-10-13T10:00:00Z", "answer": "", "closed": ""}) + "\n")
        self.root = base / "farmer-x"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / "QUESTIONS.md").write_text("## Q2 · 2026-10-09 · user · open\n\n**Q:** \"Own store?\"\n")

    def run_q(self, *args, root=None):
        env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "FARMER_DIR": str(self.state)}
        return subprocess.run(["python3", str(SCRIPT), *args], cwd=root or self.root, text=True, capture_output=True, env=env)

    def test_the_farmer_slot_prints_the_joined_list(self):
        out = self.run_q()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith("2 open questions in 2 slots\n"), out.stdout)
        self.assertIn("**05** (the farmer's list)\nQ1: Land it?\nWaits for: the landing", out.stdout)
        self.assertIn("**main** (QUESTIONS.md)\nQ2: \"Own store?\"", out.stdout)
        self.assertEqual(json.loads(self.run_q("--json").stdout)["open"], 2)
        self.assertEqual(self.run_q("--path").stdout.strip(), "QUESTIONS.md")  # --path still names the own store

    def test_another_checkout_keeps_its_own_store(self):
        other = self.root.parent / "03"
        other.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=other, check=True)
        (other / "QUESTIONS.md").write_text("## Q7 · 2026-10-09 · user · open\n\n**Q:** \"Mine?\"\n")
        self.assertEqual(self.run_q(root=other).stdout, "1 open question (QUESTIONS.md)\n\nQ7: \"Mine?\"\n")


if __name__ == "__main__":
    unittest.main()
