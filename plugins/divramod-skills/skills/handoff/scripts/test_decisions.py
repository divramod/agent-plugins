"""decisions.py lists a checkout's decisions and builds the farmer's decision check (skills plan 0008)."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "decisions.py"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t"}
PLAN = """# Plan 0003: x

## Pre-authorized

- 2026-10-05 (the user, relayed by the farmer): deploy to staging. User: "go"

## Decisions

- 2026-10-04 (user): keep sqlite,
  no postgres.
- <decisions taken while planning or grilling, with dates>

## Notes

- not a decision
"""
HANDOFF = """# Handoff

Updated 2026-10-05, branch `04`, written at `abc1234`.
Farmer: farmer-a4 (hal2)

## Plan
[Plan 0003](plans/0003-x/plan.md): 1/3 done.

## Open
- which port the server uses (waiting for the farmer)
"""


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, env=ENV, text=True, capture_output=True, check=True).stdout


class DecisionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.main = Path(self.tmp.name) / "skills"
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        git(self.main, "commit", "-q", "--allow-empty", "-m", "init")
        self.slot = Path(self.tmp.name) / "wt" / "04"
        git(self.main, "worktree", "add", "-q", "-b", "04", str(self.slot))
        (self.slot / "plans" / "0003-x").mkdir(parents=True)
        (self.slot / "plans" / "0003-x" / "plan.md").write_text(PLAN)

    def tearDown(self):
        self.tmp.cleanup()

    def run_it(self, *args):
        p = subprocess.run(["python3", str(SCRIPT), "--json", *args], cwd=self.slot, env=ENV, text=True,
                           capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_the_handoff_names_the_farmer_of_another_repo(self):
        (self.slot / "HANDOFF.md").write_text(HANDOFF)
        r = self.run_it()
        self.assertEqual((r["plan"], r["farmer"], r["farmer_repo"], r["slot"]),
                         ("plans/0003-x/plan.md", "farmer-a4", "hal2", "skills/04"))
        self.assertEqual([d["text"] for d in r["decisions"]], [
            "2026-10-04 (user): keep sqlite, no postgres.",
            '2026-10-05 (the user, relayed by the farmer): deploy to staging. User: "go"',
            "which port the server uses (waiting for the farmer)"])
        self.assertEqual(r["message"], "decision check skills/04: I have these decisions: (1) 2026-10-04 (user): "
                                       "keep sqlite, no postgres. (2) 2026-10-05 (the user, relayed by the farmer): "
                                       'deploy to staging. User: "go" (3) which port the server uses (waiting for the '
                                       "farmer). Did I forget one?")

    def test_a_subservant_slot_reports_its_lead(self):
        self.assertIsNone(self.run_it()["lead"])
        (self.slot / "plans" / "LEAD").write_text("02 0003-x 4\n")

        self.assertEqual(self.run_it()["lead"], {"slot": "02", "plan": "0003-x", "step": "4"})
        text = subprocess.run(["python3", str(SCRIPT)], cwd=self.slot, env=ENV, text=True, capture_output=True).stdout
        self.assertIn("lead: slot 02, plan 0003-x, step 4: a subservant, continue that one step only", text)

    def test_a_broken_marker_still_marks_the_slot(self):
        # review 1 finding 10: bad but marked, as the farmer reads it (prune refuses it, mtm_scan skips its landing)
        for broken in ("02 0003-x\n", "lead 0003-x 4\n", "\n"):
            (self.slot / "plans" / "LEAD").write_text(broken)
            lead = self.run_it()["lead"]
            self.assertTrue(lead["bad"], broken)
            self.assertIn("plans/LEAD is not `<lead-slot> <plan> <step>`", lead["error"])
        text = subprocess.run(["python3", str(SCRIPT)], cwd=self.slot, env=ENV, text=True, capture_output=True).stdout
        self.assertIn("lead: broken marker (plans/LEAD is not", text)
        self.assertIn("never the plan, never a landing", text)

    def test_current_plan_and_no_farmer_mean_this_repos_farmer(self):
        (self.slot / "plans" / "CURRENT_PLAN").write_text("0003-x\n")
        r = self.run_it()
        self.assertEqual((r["plan"], r["farmer"], r["farmer_repo"], r["slot"]),
                         ("plans/0003-x/plan.md", None, "skills", "04"))
        self.assertTrue(r["message"].startswith("decision check 04: I have these decisions: (1) 2026-10-04"))

    def test_nothing_found(self):
        r = self.run_it("--farmer-repo", "skills")
        self.assertEqual((r["plan"], r["decisions"]), (None, []))
        self.assertEqual(r["message"], "decision check 04: I have these decisions: none. Did I forget one?")


INDEXED_PLAN = """# Plan 0003: x

## Decisions

- 2026-10-06 (the user, via the farmer 04-9): the train waits. User: "stop the 04-train. 12 should finish first"
- 2026-10-06 (autogrill 1): bash, not python.
"""
INTENT = """# Intent

| Date | Question | Decision |
|---|---|---|
| 2026-10-06 | How are the worktrees cleaned up? | One train (the user via the farmer 04-6: "i want 06, 08 and 04 to \
be merged to main after 12. one train, 04 should take the lead") |
"""
INDEXED = """# Handoff

Updated 2026-10-06, branch `04`, written at `abc1234`.
Farmer: farmer-hal2-71 (hal2)

## Plan
[Plan 0003](plans/0003-x/plan.md): 1/3 done.

## Decisions
- 2026-10-06 "stop the 04-train. 12 should finish first" (via farmer 04-9) · home: plan Decisions · ended 2026-10-06:
  12 landed, go 04-11
- 2026-10-06 "i want 06, 08 and 04 to be merged to main after 12. one train, 04 should take the lead" (via farmer
  04-6) · home: INTENT.md 2026-10-06 row
"""


class IndexTest(unittest.TestCase):
    """Skills plan 0012: HANDOFF.md's Decisions section indexes every user decision in force."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.slot = Path(self.tmp.name) / "04"
        self.slot.mkdir()
        git(self.slot, "init", "-q", "-b", "04")
        (self.slot / "plans" / "0003-x").mkdir(parents=True)
        (self.slot / "plans" / "0003-x" / "plan.md").write_text(INDEXED_PLAN)
        (self.slot / "INTENT.md").write_text(INTENT)

    def tearDown(self):
        self.tmp.cleanup()

    def run_it(self, *args):
        return subprocess.run(["python3", str(SCRIPT), *args], cwd=self.slot, env=ENV, text=True, capture_output=True)

    def check(self, handoff):
        (self.slot / "HANDOFF.md").write_text(handoff)
        p = self.run_it("--check")
        return p.returncode, p.stdout.strip()

    def test_the_index_comes_first_and_the_plan_item_it_holds_is_not_repeated(self):
        (self.slot / "HANDOFF.md").write_text(INDEXED)
        r = json.loads(self.run_it("--json").stdout)
        self.assertEqual([(d["from"], d["text"][:30]) for d in r["decisions"]], [
            ("HANDOFF.md Decisions", '2026-10-06 "stop the 04-train.'),
            ("HANDOFF.md Decisions", '2026-10-06 "i want 06, 08 and '),
            ("plan Decisions", "2026-10-06 (autogrill 1): bash")])
        self.assertIn("ended 2026-10-06: 12 landed, go 04-11", r["message"])

    def test_a_complete_index_passes_the_check(self):
        self.assertEqual(self.check(INDEXED), (0, "ok"))
        self.assertEqual(self.check("# Handoff\n\n## Decisions\n- none\n"), (0, "ok"))

    def test_a_handoff_without_the_section_fails(self):
        code, out = self.check("# Handoff\n\n## Next\n1. go on\n")
        self.assertEqual(code, 1)
        self.assertIn("no `## Decisions` section", out)

    def test_each_line_needs_date_quote_and_a_home_that_holds_the_quote(self):
        code, out = self.check(INDEXED.split("## Decisions")[0] + """## Decisions
- "stop the 04-train. 12 should finish first" · home: plan
- 2026-10-06 the user said to wait · home: plan
- 2026-10-06 "no fail fast at the first red job please" (via farmer 12-51) · home: plan
- 2026-10-06 "stop the 04-train. 12 should finish first" · home: .adr/missing.md
- 2026-10-06 "stop the 04-train. 12 should finish first" (via farmer 04-9)
- 2026-10-06 "stop the 04-train. 12 should finish first" · home: plan · ended: 12 landed
""")
        self.assertEqual(code, 1)
        lines = out.splitlines()
        self.assertEqual([line.split(":")[0] for line in lines], [f"Decisions line {n}" for n in range(1, 7)])
        self.assertIn("no date", lines[0])
        self.assertIn("quotes no user's words", lines[1])
        self.assertIn("does not hold the quote", lines[2])
        self.assertIn("no existing file", lines[3])
        self.assertIn("names no home", lines[4])
        self.assertIn("`ended` without a date", lines[5])

    def test_quotes_match_across_case_whitespace_and_punctuation(self):
        spec = __import__("importlib.util").util.spec_from_file_location("decisions", SCRIPT)
        mod = __import__("importlib.util").util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(mod.found("Stop the 04-train!  12 should finish first", "stop the 04 train; 12 should\nfinish first"))
        self.assertFalse(mod.found("stop the 04-train. 12 should finish first", "stop the 04 train later"))
        self.assertIsNone(mod.found("1", "1"))
        long = "i want 06, 08 and 04 to be merged to main after 12. one train, 04 should take the lead. are there others?"
        self.assertTrue(mod.found(long, INTENT))


if __name__ == "__main__":
    unittest.main()
