"""The superseded-step rewrite (plan 0592's D15): `since` names the step a later decision of another plan
superseded, the model's verdicts are written before any code: the plan's own ledger entry with the outside link, the
replaced own entry `superseded` with `By:`, the row and its step file."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import continue_testkit as kit  # noqa: E402
import rewrite  # noqa: E402

GATHER = __import__("importlib").import_module("continue")
OUTSIDE = {"plan": "0002-y", "id": "D4", "date": "2026-11-02", "who": "user", "state": "in-force", "by": None,
           "text": "No report goes out by mail any more; the view shows it.", "answer": None,
           "path": "plans/0002-y/decisions.md", "why": [{"kind": "link", "what": "names plan 0001", "step": None},
                                                         {"kind": "words", "what": "mail, report", "step": "2"}],
           "steps": ["2"]}
VERDICTS = {"entries": [{"id": "e1", "text": "The report is shown in the view, never mailed.",
                         "why": "the user's later decision", "link": "[0002 D4](../0002-y/decisions.md)",
                         "supersedes": ["D2"]}],
            "steps": [{"step": "2", "verdict": "superseded", "by": "e1", "note": "no mail any more"},
                      {"step": "3", "verdict": "changed", "by": "e1", "row": "Show the report in the view, no mail",
                       "done_when": "the view test green, no mail sent"}]}


class SupersededStep(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.farm = kit.Farm(self.tmp / "farm")
        self.field = self.farm.field("07", plan="0001-x")
        self.plan = self.field / "plans/0001-x"
        self.fakes = self.tmp / "fakes"
        self.env = {**kit.fakes(self.fakes), "PAUSE_ROOT": str(self.tmp / "pause")}
        kit.answer(self.fakes, "role/07.json", kit.role_doc(self.field, "foreman"))
        kit.answer(self.fakes, "since/0001-x.json", kit.since_doc("0001-x", decisions=[OUTSIDE]))

    def rewrite(self, verdicts, field=None):
        return subprocess.run([sys.executable, str(HERE / "continue.py"), "rewrite", "--verdicts", "-", "--repo",
                               str(field or self.field)], input=json.dumps(verdicts), capture_output=True, text=True,
                              env={**os.environ, **self.env})

    def test_since_names_the_superseded_step_before_any_code(self):
        with mock.patch.dict(os.environ, self.env):
            check = GATHER.gather(self.field)["check"]
        self.assertEqual(check["state"], "judge")
        self.assertEqual(check["steps"], {"2": ["0002-y D4"], "3": []})
        self.assertEqual(check["items"][0]["strength"], "strong")

    def test_the_verdicts_rewrite_ledger_rows_and_step_files(self):
        done = self.rewrite(VERDICTS)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["entries"], ["D3"])
        ledger = (self.plan / "decisions.md").read_text()
        self.assertIn("## D2 · 2026-11-01 · agent · superseded", ledger)
        self.assertIn("**Why:** the user reads mail.\n**By:** D3\n", ledger)
        self.assertRegex(ledger, r"## D3 · \d{4}-\d\d-\d\d · agent · in-force\n\n\*\*D:\*\* The report is shown")
        self.assertIn("**Why:** the user's later decision; from [0002 D4](../0002-y/decisions.md)", ledger)
        plan = (self.plan / "plan.md").read_text()
        self.assertIn("| 2 | Send the report by mail | a mail goes out | sonnet | medium | 1m | 100k | done: superseded "
                      "by D3 |", plan)
        self.assertIn("| 3 | Show the report in the view, no mail | the view test green, no mail sent |", plan)
        self.assertIn("| 1 | Write the parser | parser tests green | sonnet | medium | 1m | 100k | done |", plan)
        step = (self.plan / "steps/2.md").read_text()
        self.assertTrue(step.index("## Task") < step.index("## Approach") < step.index("## Notes"))
        self.assertRegex(step, r"- \d{4}-\d\d-\d\d: superseded by D3 \(the consistency check of /continue\): "
                               r"no mail any more\n$")
        self.assertIn("changed by D3", (self.plan / "steps/3.md").read_text())

    def test_a_second_rewrite_adds_to_the_notes(self):
        self.rewrite(VERDICTS)
        again = {"entries": [{"text": "Mail stays off.", "link": "x"}], "steps": [{"step": "3", "verdict": "valid"}]}
        done = self.rewrite(again)
        self.assertEqual(json.loads(done.stdout)["entries"], ["D4"])
        self.assertEqual((self.plan / "steps/2.md").read_text().count("## Notes"), 1)

    def test_a_servant_never_rewrites_the_plan(self):
        servant = self.farm.field("31", plan="0001-x", lead="07 0001-x 3")
        kit.answer(self.fakes, "role/31.json", kit.role_doc(servant, "servant"))
        done = self.rewrite(VERDICTS, servant)
        self.assertEqual(done.returncode, 1)
        self.assertIn("reports the verdicts to its foreman", done.stderr)

    def test_bad_verdicts_change_nothing(self):
        before = [(self.plan / name).read_text() for name in ("plan.md", "decisions.md", "steps/2.md")]
        for bad in ({"steps": [{"step": "2", "verdict": "maybe"}]}, {"entries": [{"text": " "}]},
                    {"entries": [{"text": "x"}], "steps": [{"step": "9", "verdict": "superseded"}]},
                    {"entries": [{"text": "x", "supersedes": ["D9"]}], "steps": [{"step": "2", "verdict": "superseded"}]}):
            with self.assertRaises(rewrite.Refused):
                rewrite.apply(self.plan / "plan.md", self.plan / "decisions.md", bad)
        self.assertEqual([(self.plan / n).read_text() for n in ("plan.md", "decisions.md", "steps/2.md")], before)

    def test_a_schema_2_plan_is_refused(self):
        plan = self.plan / "plan.md"
        plan.write_text(plan.read_text().replace("schema: 1", "schema: 2"))
        with self.assertRaises(rewrite.Refused):
            rewrite.apply(plan, self.plan / "decisions.md", {"steps": [{"step": "2", "verdict": "superseded"}]})


if __name__ == "__main__":
    unittest.main()
