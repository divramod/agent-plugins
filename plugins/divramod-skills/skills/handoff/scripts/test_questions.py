"""questions.py finds a checkout's questions file, lists its open questions and checks its entries."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "questions.py"
FILE = """# Questions and answers

## Q1 · 2026-10-07 · agent · answered 2026-10-07

**Q:** Windows code signing: a) unsigned for now b) a certificate?
**A:** User: "unsigned for now"

## Q2 · 2026-10-07 · user · open

**Q:** "Okay now tell me if you had success in installing something
on the Windows machine"

## Q3 · 2026-10-07 · agent · dropped 2026-10-08

**Q:** May the milestones land themselves?
**A:** no longer needed: the plan lands once.
"""


class Questions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / "plans" / "0003-x").mkdir(parents=True)
        (self.root / "plans" / "0003-x" / "plan.md").write_text("# Plan 0003: x\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        return subprocess.run(["python3", str(SCRIPT), *args], cwd=self.root, text=True, capture_output=True)

    def test_the_file_is_the_current_plans(self):
        (self.root / "plans" / "CURRENT_PLAN").write_text("0003-x\n")
        self.assertEqual(self.run_script("--path").stdout.strip(), "plans/0003-x/questions.md")

    def test_the_file_is_the_plan_the_handoff_links_when_current_plan_names_a_task(self):
        (self.root / "plans" / "CURRENT_PLAN").write_text("fix-login-timeout\n")
        (self.root / "HANDOFF.md").write_text("## Plan\n[x](plans/0003-x/plan.md): 1/2 done\n")
        self.assertEqual(self.run_script("--path").stdout.strip(), "plans/0003-x/questions.md")

    def test_work_without_a_plan_keeps_it_in_plans(self):
        self.assertEqual(self.run_script("--path").stdout.strip(), "plans/questions.md")

    def test_no_file_is_no_question(self):
        out = self.run_script()
        self.assertEqual(out.returncode, 0)
        self.assertIn("0 open, 0 answered", out.stdout)
        self.assertEqual(self.run_script("--check").stdout.strip(), "ok")

    def test_lists_the_open_questions_only(self):
        (self.root / "plans" / "CURRENT_PLAN").write_text("0003-x\n")
        (self.root / "plans" / "0003-x" / "questions.md").write_text(FILE)
        out = self.run_script().stdout
        self.assertIn('Q2 (user, 2026-10-07): "Okay now tell me if you had success in installing something on the '
                      'Windows machine"', out)
        self.assertNotIn("Q1 ", out)
        self.assertIn("1 open, 2 answered or dropped", out)
        data = json.loads(self.run_script("--json").stdout)
        self.assertEqual([e["n"] for e in data["open"]], [2])
        self.assertEqual(data["next"], 4)
        self.assertEqual(self.run_script("--check").stdout.strip(), "ok")

    def test_check_names_every_problem(self):
        (self.root / "plans" / "questions.md").write_text(
            "## Q1 · 2026-10-07 · agent · answered 2026-10-07\n\n**Q:** a?\n\n"
            "## Q1 · 2026-10-07 · user · open\n\n**Q:** b?\n**A:** yes\n\n"
            "## Q2 - today - me - open\n\n**Q:** c?\n\n"
            "## Q3 · 2026-10-07 · agent · open\n\nno question line\n")
        out = self.run_script("--check")
        self.assertEqual(out.returncode, 1)
        for part in ("Q1: answered, but no **A:** line", "Q1: the number is used twice",
                     "Q1: open, but it has an answer", "heading does not match", "Q3: no **Q:** line"):
            self.assertIn(part, out.stdout)


if __name__ == "__main__":
    unittest.main()
