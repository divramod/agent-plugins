"""prune.py plan (hal2 plan 0377 step 4): the CLI on the scratch farm behind fake CLIs, exits 0, 1 and 2, `--json`,
`--field`. Nothing is changed by `plan`."""

import contextlib
import io
import json
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import facts
import prune
import test_facts


class PlanCli(test_facts.Farm):
    def setUp(self):
        super().setUp()
        real = facts.collect
        self.asked = []

        def fake(main, only=None, **kw):
            self.asked.append(kw.get("cached_sizes", False))
            return real(main, only=only, build=lambda path: False, measure=self.sizes, lookup=lambda plan, repos: "finished")

        for p in (mock.patch.object(facts, "collect", side_effect=fake), mock.patch.object(facts, "missing_tools", return_value=[]),
                  mock.patch.object(facts, "disk", return_value={"free_gb": 90.0, "used_pct": 95.0, "total_gb": 1000.0})):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = prune.main(["plan", "--repo", str(self.main), *args])
        return code, out.getvalue(), err.getvalue()

    def test_plan_json_has_the_plan_and_the_facts(self):
        code, out, _ = self.run_cli("--json", "--field", "03", "--field", "05")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual([f["slot"] for f in data["facts"]["fields"]], ["03", "05"])
        self.assertEqual(list(data["plan"]["jobs"]), ["stale-pointers", "phase-1", "phase-2", "phase-3"])
        self.assertEqual([(a["field"], a["action"]) for a in data["plan"]["jobs"]["stale-pointers"]["actions"]],
                         [("05", "clear-pointer")])
        self.assertTrue(data["plan"]["short"])

    def test_cached_sizes_is_passed_to_the_facts(self):
        self.run_cli("--json", "--cached-sizes", "--field", "03")
        self.run_cli("--json", "--field", "03")
        self.assertEqual(self.asked, [True, False])

    def test_plan_text_lists_the_facts_and_the_would_lines(self):
        code, out, _ = self.run_cli("--field", "03")
        self.assertEqual(code, 0)
        self.assertIn("03 keeper: no session; free;", out)
        self.assertIn("would muck out 03", out)
        self.assertIn("phase-3: skipped: no candidate", out)

    def test_a_missing_tool_is_exit_2(self):
        with mock.patch.object(facts, "missing_tools", return_value=["hal2-cli-plans"]):
            code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("hal2-cli-plans", err)

    def test_an_unreadable_answer_is_exit_1(self):
        with mock.patch.object(facts, "collect", side_effect=facts.FactsError("no worktrees")):
            code, _, err = self.run_cli()
        self.assertEqual((code, err), (1, "prune: no worktrees\n"))


if __name__ == "__main__":
    unittest.main()
