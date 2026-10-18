"""questions.py finds a checkout's questions file, lists its open questions and checks its entries."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import handoff_testkit as kit

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

    def run_script(self, *args, cli=None):
        """The script with hal2-cli-plans pinned: `cli` (a stub script), else none (the fallback rule)."""
        env = {**os.environ, "HAL2_CLI_PLANS": cli or str(self.root / "no-such-cli")}
        return kit.run(["python3", str(SCRIPT), *args], cwd=self.root, env=env)

    def stub(self, stdout: str, code: int = 1) -> str:
        """A fake hal2-cli-plans that prints `stdout` and exits `code`; it records its arguments."""
        path = self.root / "stub-cli"
        path.write_text(f"#!/bin/sh\necho \"$@\" > '{self.root}/stub-args'\ncat <<'EOF'\n{stdout}\nEOF\nexit {code}\n")
        path.chmod(0o755)
        return str(path)

    def write_store(self, text: str) -> Path:
        (self.root / "plans" / "CURRENT_PLAN").write_text("0003-x\n")
        store = self.root / "plans" / "0003-x" / "questions.md"
        store.write_text(text)
        return store

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

    def test_raw_entries_keep_the_option_lines_and_the_closing_date(self):
        import questions
        raw = questions.raw_entries(FILE + "\n## Q4 · 2026-10-09 · agent · open\n\n**Q:** Pick one?\n"
                                    "  a) (Recommended) yes — x\n  b) no — y\n**Decision:** D1\n")
        self.assertEqual(raw[4]["question"], "Pick one?\n  a) (Recommended) yes — x\n  b) no — y")
        self.assertEqual(raw[4]["closed"], "")
        self.assertEqual(raw[1]["closed"], "2026-10-07")
        self.assertEqual(raw[3]["closed"], "2026-10-08")

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

    def test_check_fallback_reports_an_open_agent_question_not_in_the_q_form(self):
        """Without hal2-cli-plans: inline options, a wrong count and a missing mark are problems of open agent
        entries only (answered ones, the user's and the well-formed pass)."""
        self.write_store(FILE + "\n## Q4 · 2026-10-14 · agent · open\n\n**Q:** Pick? a) yes b) no c) maybe\n"
                         "\n## Q5 · 2026-10-14 · agent · open\n\n**Q:** Two?\n  a) (Recommended) yes\n  b) no\n"
                         "\n## Q6 · 2026-10-14 · agent · open\n\n**Q:** No mark?\n  a) yes\n  b) no\n  c) so\n"
                         "\n## Q7 · 2026-10-14 · agent · open\n\n**Q:** Fine?\n  a) (Recommended) yes\n  b) no\n  c) so\n")
        out = self.run_script("--check")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(out.stdout.splitlines(), [
            "Q4: its options a) b) c) are inline in the question; the Q form puts each on its own line",
            "Q5: 2 option lines; the Q form needs exactly three, a) b) c), each on its own line",
            'Q6: option a) is not marked "(Recommended)"; the Q form recommends the first'])

    def test_a_sentence_that_mentions_a_letter_is_not_torn(self):
        self.write_store("## Q1 · 2026-10-14 · agent · open\n\n**Q:** Is plan a) done?\n  a) (Recommended) yes\n"
                         "  b) no\n  c) so\n")
        self.assertEqual(self.run_script("--check").stdout.strip(), "ok")

    def test_check_uses_the_cli_when_it_is_there(self):
        store = self.write_store(FILE)
        line = "Q2: 0 option lines; the Q form needs exactly three, a) b) c), each on its own line"
        out = self.run_script("--check", cli=self.stub(json.dumps({"problems": [{"n": 2, "message": line[4:]}]})))
        self.assertEqual((out.returncode, out.stdout.strip()), (1, line))
        self.assertEqual((self.root / "stub-args").read_text().strip(), f"questions check --json --store {store}")

    def test_check_uses_the_cli_json_when_it_is_there(self):
        self.write_store(FILE)
        cli = self.stub(json.dumps({"store": "x", "problems": [{"n": 4, "message": "inline"}, {"message": "bad head"}]}))
        out = self.run_script("--check", cli=cli)
        self.assertEqual((out.returncode, out.stdout.splitlines()), (1, ["Q4: inline", "bad head"]))
        self.assertEqual(self.run_script("--check", cli=self.stub(json.dumps({"problems": []}), 0)).stdout.strip(), "ok")

    def test_an_older_cli_without_questions_falls_back(self):
        self.write_store(FILE + "\n## Q4 · 2026-10-14 · agent · open\n\n**Q:** Pick? a) yes b) no c) maybe\n")
        out = self.run_script("--check", cli=self.stub("hal2-cli-plans: unknown command", 2))
        self.assertIn("Q4: its options a) b) c) are inline", out.stdout)


if __name__ == "__main__":
    unittest.main()
