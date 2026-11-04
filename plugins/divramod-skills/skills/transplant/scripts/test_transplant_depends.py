"""transplant and the plans that wait for its plan (hal2 plan 0595 step 13): a transplant moves the branch, so the
plan.md with its `depends_on` goes along, and the graph (read live from the fields) shows the dependents under the
new field; `check` names them and never stops for them. The CLI is a stub; the scratch farm is git only."""
import unittest

from test_support import OK, Scratch, sh

LINK = {"plan": "0600", "slug": "0600-later", "field": "12", "steps": [], "needs": [], "until": "main",
        "state": "pushed", "reached": False}


def node(field, state="pushed"):
    return {"plan": "0595", "slug": "0595-gaps", "field": field, "depends_on": [],
            "dependents": [{**LINK, "state": state}]}


class TestDependents(Scratch):
    def test_check_names_what_waits_and_does_not_stop(self):
        self.graph(node("34"))
        code, result, _ = self.run_script("check", "09", repo=self.f34)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["dependents"], ["plan 0600 waits for plan 0595 until main (now pushed)"])
        self.assertTrue(any("follows the plan to field 09" in n for n in result["notes"]), result["notes"])

    def test_a_dependent_already_satisfied_or_another_field_is_not_named(self):
        self.graph(node("34", state="main"), node("07"))
        code, result, _ = self.run_script("check", "09", repo=self.f34)
        self.assertEqual((code, result["dependents"]), (0, []))

    def test_without_the_command_the_check_goes_on_with_one_advisory_line(self):
        (self.bin / "hal2-cli-plans").write_text("#!/bin/sh\necho 'unknown command' >&2\nexit 2\n")
        code, result, _ = self.run_script("check", "09", repo=self.f34)
        self.assertEqual((code, result["dependents"]), (0, []))
        self.assertTrue(any(n.startswith("plan dependents not checked") for n in result["notes"]), result["notes"])

    def test_the_graph_is_read_live_so_the_dependents_follow_the_plan_to_the_new_field(self):
        import importlib
        import os
        import transplant
        importlib.reload(transplant)
        os.environ["FAKE_DIR"] = str(self.fake)
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{old}"
        self.addCleanup(os.environ.__setitem__, "PATH", old)
        self.graph(node("34"))
        self.assertEqual(list(transplant.dependents.by_field(transplant.dependents.graph(self.app)[0])), ["34"])
        self.graph(node("09"))  # the transplant moved the plan: the same graph, the other field
        held = transplant.dependents.by_field(transplant.dependents.graph(self.app)[0])
        self.assertEqual(list(held), ["09"])
        self.assertEqual(len(self.plan_calls()), 2)  # once per view, no cache

    def plan_calls(self):
        import json
        log = self.fake / "plans-log"
        return [json.loads(x) for x in log.read_text().splitlines()]

    def test_the_branch_carries_plan_md_with_its_depends_on(self):
        plan = self.f34 / "plans/0595-gaps/plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("---\ndepends_on:\n  - plan: 0510\n    until: pushed\n---\n# plan\n")
        sh(self.f34, "add", "-A")
        sh(self.f34, "commit", "-q", "-m", "plan")
        sh(self.app, "branch", "-f", "09-moved", "34")  # the branch's tip lands in the target: one commit, one plan.md
        moved = sh(self.app, "show", "09-moved:plans/0595-gaps/plan.md")
        self.assertIn("depends_on:\n  - plan: 0510\n    until: pushed", moved)


if __name__ == "__main__":
    unittest.main()
