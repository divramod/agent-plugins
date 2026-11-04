"""Prune and the plans that wait for a field's plan (hal2 plan 0595 step 13): a field whose plan has an open dependent
(a Link whose `state` is not `main`) is not free, whatever else the proof says, and the reason names the dependents.
`hal2-cli-plans depends list` is the fake CLI's (fake_clis.py); a missing or older one is one advisory line."""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import facts
import fake_clis


def node(field, state="pushed"):
    return {"plan": "0595", "slug": "0595-gaps", "field": field, "depends_on": [],
            "dependents": [{"plan": "0600", "slug": "0600-later", "field": "12", "steps": [], "needs": [],
                            "until": "main", "state": state, "reached": state == "main"}]}


class Guard(fake_clis.Farm):
    def test_a_field_with_an_open_dependent_is_not_removed_and_the_reason_names_it(self):
        self.add("23")
        self.add("24")
        self.feed(depends=[node("23")])
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        self.assertTrue((self.base / "23").exists())
        self.assertFalse((self.base / "24").exists(), "an unrelated free field is still removed")
        self.assertEqual(self.calls(), [["worktree", "remove", "24", "--remote"]])

    def test_the_proof_says_why(self):
        self.add("23")
        self.feed(depends=[node("23")])
        found = facts.collect(str(self.main))
        field = found["fields"][0]
        self.assertFalse(field["free"])
        self.assertEqual(field["proof"], "its plan has open dependents: plan 0600 waits for plan 0595 until main "
                                         "(now pushed)")

    def test_a_dependent_whose_dependency_reached_main_does_not_hold_the_field(self):
        self.add("23")
        self.feed(depends=[node("23", state="main")])
        self.assertTrue(facts.collect(str(self.main))["fields"][0]["free"])

    def test_the_graph_is_read_once_per_view(self):
        self.add("23")
        self.add("24")
        self.feed(depends=[node("23")])
        facts.collect(str(self.main))
        self.assertEqual(len(self.calls("hal2-cli-plans", "depends")), 1)

    def test_an_older_cli_gives_one_advisory_line_and_no_refusal(self):
        self.add("23")  # the fake knows no `depends`: it exits 1
        found = facts.collect(str(self.main))
        self.assertTrue(found["fields"][0]["free"])
        self.assertEqual(len(found["advice"]), 1)
        self.assertIn("plan dependents not checked", found["advice"][0])
