"""The handoff of a plan in the record format: its place, its stamp, the ledger as the decisions index, and the
scripts that follow it (hal2 plan 0206 step 8)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN = HERE.parents[1] / "plan" / "scripts" / "plan.py"
sys.path.insert(0, str(PLAN.parent))
import checker  # noqa: E402  (the plan skill's: hal2's records checker, hal2 plan 0214 step 6)

needs_checker = unittest.skipUnless(checker.binary(), f"{checker.NAME} is not installed and ${checker.ENV} is unset")
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
LEGACY = "# Plan 0001: old\n\n## Decisions\n\n- none\n\n| # | Step | Status |\n|---|---|---|\n| 1 | x | next |\n"
ENTRY = """
## D1 · 2026-10-08 · user · in-force

**D:** Nothing lands tonight.
**Words:** "i do the mtm next morning, dont want to destroy something"

## D2 · 2026-10-08 · agent · superseded

**D:** The handoff stays at the root.
**By:** D3

## D3 · 2026-10-08 · agent · in-force

**D:** The handoff lives in the plan folder.
**Why:** It is committed with the plan.
"""


class RecordHandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name).resolve()
        self.run_in("git", "init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("1\n")
        self.commit_all("init")

    def tearDown(self):
        self.tmp.cleanup()

    def run_in(self, *args, check=True) -> subprocess.CompletedProcess:
        return subprocess.run(args, cwd=self.repo, env=ENV, text=True, capture_output=True, check=check)

    def script(self, name: str, *args) -> subprocess.CompletedProcess:
        runner = ["bash"] if name.endswith(".sh") else [sys.executable]
        return self.run_in(*runner, str(HERE / name), *args, check=False)

    def commit_all(self, message: str) -> str:
        self.run_in("git", "add", "-A")
        self.run_in("git", "commit", "-qm", message)
        return self.run_in("git", "rev-parse", "--short", "HEAD").stdout.strip()

    def new_plan(self) -> Path:
        out = self.run_in(sys.executable, str(PLAN), "new", "Tiny").stdout
        return self.repo / json.loads(out)["path"]

    def legacy_plan(self) -> Path:
        plan = self.repo / "plans" / "0001-old" / "plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(LEGACY)
        (self.repo / "plans" / "CURRENT_PLAN").write_text("0001-old\n")
        return plan

    def checked(self) -> str:
        """`decisions.py --check`'s verdict, its advisory line (no checker installed) left out."""
        lines = self.script("decisions.py", "--check").stdout.strip().split("\n")
        return "\n".join(line for line in lines if line != checker.NOT_INSTALLED)

    def where(self) -> dict:
        return json.loads(self.script("where.py", "--json").stdout)

    def test_a_record_plan_keeps_its_handoff_and_its_decisions_in_its_folder(self):
        self.new_plan()
        self.assertEqual(self.where(), {
            "file": "plans/0001-tiny/handoff.md", "form": "record", "plan": "plans/0001-tiny/plan.md",
            "decisions": "plans/0001-tiny/decisions.md", "questions": "plans/0001-tiny/questions.md"})
        self.assertEqual(self.script("questions.py", "--path").stdout.strip(), "plans/0001-tiny/questions.md")

    def test_a_legacy_plan_no_plan_and_a_subservant_keep_the_root_handoff(self):
        self.assertEqual((self.where()["file"], self.where()["questions"]), ("HANDOFF.md", "plans/questions.md"))
        self.legacy_plan()
        self.assertEqual((self.where()["file"], self.where()["form"]), ("HANDOFF.md", "legacy"))
        (self.repo / "plans" / "CURRENT_PLAN").write_text("shooter/1/some-shot\n")
        self.assertEqual(self.where()["plan"], None)

    def test_a_subservant_never_writes_the_leads_handoff(self):
        self.new_plan()
        (self.repo / "plans" / "LEAD").write_text("30 0001-tiny 2\n")
        self.assertEqual((self.where()["file"], self.where()["form"]), ("HANDOFF.md", "legacy"))

    def test_stamp_writes_a_missing_handoff_and_says_where_it_was_written(self):
        plan = self.new_plan()
        sha = self.commit_all("the plan")
        handoff = plan.parent / "handoff.md"
        handoff.unlink()
        self.assertEqual(self.script("where.py", "--stamp").stdout.strip(), "plans/0001-tiny/handoff.md")
        text = handoff.read_text()
        self.assertIn(f'\nat: "{sha}"\n', text)
        self.assertIn("\nbranch: main\n", text)
        self.assertEqual(self.checked(), "ok")

    def test_since_reads_the_plans_handoff_and_its_at(self):
        self.new_plan()
        self.commit_all("the plan")
        self.script("where.py", "--stamp")
        self.commit_all("docs: the handoff")
        self.assertIn("commits since: none", self.script("since.sh").stdout)
        (self.repo / "a.txt").write_text("2\n")
        self.commit_all("another session worked")
        out = self.script("since.sh").stdout
        self.assertIn("another session worked", out)
        self.assertNotIn("docs: the handoff", out)

    def test_the_ledger_is_the_decisions_index(self):
        plan = self.new_plan()
        ledger = plan.parent / "decisions.md"
        ledger.write_text(ledger.read_text() + ENTRY)
        self.assertEqual(self.checked(), "ok")
        listed = json.loads(self.script("decisions.py", "--json").stdout)["decisions"]
        texts = [d["text"] for d in listed if d["from"] == "decisions.md"]
        self.assertEqual(len(texts), 2, texts)
        self.assertIn('Nothing lands tonight. Words: "i do the mtm next morning', texts[0])
        self.assertTrue(texts[1].startswith("D3 2026-10-08 (agent, in-force): The handoff lives in the plan folder."))

    @needs_checker
    def test_check_names_a_broken_ledger_entry(self):
        plan = self.new_plan()
        ledger = plan.parent / "decisions.md"
        ledger.write_text(ledger.read_text() + ENTRY.replace("**By:** D3\n", ""))
        result = self.script("decisions.py", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("plans/0001-tiny/decisions.md: D2: a **By:** line exactly when the entry is `superseded`",
                      result.stdout)

    def test_a_decision_link_in_a_question_is_no_part_of_its_answer(self):
        plan = self.new_plan()
        q = plan.parent / "questions.md"
        q.write_text(q.read_text() + "\n## Q1 · 2026-10-08 · agent · answered 2026-10-08\n\n**Q:** Land tonight?\n"
                     '**A:** "no"\n**Decision:** D1\n\n## Q2 · 2026-10-08 · agent · open\n\n**Q:** Which base?\n')
        self.assertEqual(self.script("questions.py", "--check").stdout.strip(), "ok")
        out = json.loads(self.script("questions.py", "--json").stdout)
        self.assertEqual(([e["n"] for e in out["open"]], out["answered"], out["next"]), ([2], 1, 3))

    def legacy_handoff(self, line: str) -> subprocess.CompletedProcess:
        (self.repo / "HANDOFF.md").write_text(f"# Handoff\n\n## Decisions\n\n{line}\n")
        return self.script("decisions.py", "--check")

    def test_a_legacy_home_plan_is_the_plan_or_its_ledger(self):
        plan = self.legacy_plan()
        line = '- 2026-10-08 "none of them gets servants tonight please" (the user) · home: plan'
        self.assertIn("does not hold the quote", self.legacy_handoff(line).stdout)
        (plan.parent / "decisions.md").write_text('**Words:** "none of them gets servants tonight please"\n')
        self.assertEqual(self.legacy_handoff(line).stdout.strip(), "ok")

    def test_a_generated_decision_log_is_no_home(self):
        self.legacy_plan()
        (self.repo / "INTENT.md").write_text("# Intent\n\n## Decision log\n\n<!-- generated: decision-log -->\n"
                                             "| Date | Decision | Record |\n<!-- /generated -->\n")
        out = self.legacy_handoff('- 2026-10-08 "every feature works on windows from the start" (the user) · '
                                  "home: INTENT.md").stdout
        self.assertIn("has a generated decision log, which holds no quote", out)

    def test_commit_anchors_the_ignore_line_and_commits_the_plans_handoff(self):
        plan = self.new_plan()
        (self.repo / ".gitignore").write_text("target/\nHANDOFF.md\nplans/CURRENT_PLAN\n")
        (self.repo / "HANDOFF.md").write_text("root state\n")
        handoff = "plans/0001-tiny/handoff.md"
        result = self.script("commit-handoff.sh", "docs: record decisions", str(plan), handoff)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.repo / ".gitignore").read_text(), "target/\n/HANDOFF.md\nplans/CURRENT_PLAN\n")
        names = self.run_in("git", "show", "--name-only", "--format=", "HEAD").stdout.split()
        self.assertEqual(sorted(names), [".gitignore", handoff, "plans/0001-tiny/plan.md"])
        self.assertEqual(self.run_in("git", "check-ignore", "-q", handoff, check=False).returncode, 1)
        self.assertEqual(self.run_in("git", "check-ignore", "-q", "HANDOFF.md", check=False).returncode, 0)

    def test_commit_writes_an_anchored_line_into_a_repository_without_one(self):
        (self.repo / "doc.md").write_text("x\n")
        self.script("commit-handoff.sh", "docs: record decisions", "doc.md")
        self.assertIn("\n/HANDOFF.md\n", "\n" + (self.repo / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
