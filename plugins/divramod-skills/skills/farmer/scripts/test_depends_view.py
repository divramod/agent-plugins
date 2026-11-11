"""Hal2 plan 0595 step 9: the plan dependency reader of the farmer's views, over a stub for `hal2-cli-plans depends list`;
never the real farm."""

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import depends_view as dv
import mtm_scan

LINK = {"plan": 514, "slug": "0514-x", "field": "38", "steps": [], "needs": ["3"], "until": "pushed", "state": "open", "reached": False}
GRAPH = {"schema": 1, "farm": "f", "problems": [], "plans": [
    {"plan": 543, "slug": "0543-agents", "field": "57", "depends_on": [{**LINK, "steps": ["22-27", "36"]}], "dependents": []},
    {"plan": 514, "slug": "0514-x", "field": "38", "depends_on": [],
     "dependents": [{**LINK, "plan": 543, "slug": "0543-agents", "field": "57", "steps": ["22-27", "36"]}]},
    {"plan": 581, "slug": "0581-y", "field": None, "depends_on": [{**LINK, "plan": 571, "field": None, "state": "main", "reached": True}], "dependents": []}]}


def stub(directory: Path, body: str, code: int = 0) -> str:
    path = directory / "hal2-cli-plans-stub"
    path.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.write({body!r})\nsys.exit({code})\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


class Reader(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def read(self, body: str, code: int = 0):
        with mock.patch.dict(os.environ, {"HAL2_CLI_PLANS": stub(self.dir, body, code)}):
            return dv.read(str(self.dir))

    def test_the_graph_by_plan_number(self):
        got = self.read(json.dumps(GRAPH))
        self.assertEqual(sorted(got), [514, 543, 581])
        self.assertEqual(dv.node_of(got, "0543-agents")["depends_on"][0]["plan"], 514)
        self.assertEqual(dv.node_of(got, "0999-none"), {"depends_on": [], "dependents": []})
        self.assertEqual(dv.node_of(None, "0543"), {"depends_on": [], "dependents": []})

    def test_a_missing_older_or_garbled_cli_is_unknown_never_an_error(self):
        self.assertIsNone(self.read("", 2))  # an older CLI: unknown command
        self.assertIsNone(self.read("not json"))
        self.assertIsNone(self.read('{"plans": "x"}'))
        with mock.patch.dict(os.environ, {"HAL2_CLI_PLANS": str(self.dir / "nothing-here")}):
            self.assertIsNone(dv.read(str(self.dir)))
        self.assertEqual(self.read('{"schema": 1, "plans": []}'), {})  # a farm with no dependency is known

    def test_cells(self):
        node = dv.node_of({n["plan"]: n for n in GRAPH["plans"]}, 543)
        self.assertEqual(dv.cell(node["depends_on"]), "0514 (38, open)")
        self.assertEqual(dv.cell([{**LINK, "field": None}, {**LINK, "plan": 571, "field": "09", "state": "main"}]),
                         "0514 (open), 0571 (09, main)")
        self.assertEqual(dv.cell([]), "")
        self.assertEqual(dv.cell([{**LINK, "plan": 628, "field": "09", "state": "hitched", "reached": True}]),
                         "0628 (09, hitched)")

    def test_wait_holds_only_the_next_step_it_names(self):
        node = {"depends_on": [{**LINK, "steps": ["22-27", "36"]}]}
        self.assertEqual(dv.wait_of(node, "23"), "waits for 0514 (open)")
        self.assertEqual(dv.wait_of(node, "36"), "waits for 0514 (open)")
        self.assertEqual(dv.wait_of(node, "28"), "")  # not one of the waiting steps
        self.assertEqual(dv.wait_of(node, None), "waits for 0514 (open)")  # next step unknown: the safe reading
        whole = {"depends_on": [{**LINK, "state": "pushed"}]}
        self.assertEqual(dv.wait_of(whole, "1"), "waits for 0514 (pushed)")  # a plan-level link holds every step
        done = {"depends_on": [{**LINK, "state": "main", "reached": True}]}
        self.assertEqual(dv.wait_of(done, "1"), "")
        hitched = {"depends_on": [{**LINK, "state": "hitched", "until": "main", "reached": True, "head": "c7d1003970"}]}
        self.assertEqual(dv.wait_of(hitched, "1"), "")  # a hitched link is met: it no longer waits for main

    def test_the_farmers_summary_table_gains_the_columns(self):
        snap = {"now": 0, "load": {"load1": 0.1, "cores": 8}, "queue": [], "findings": [], "landings": [],
                "worktrees": [{"slot": "57", "ahead": 1, "agent_state": "idle", "plan": "0543-agents"},
                              {"slot": "38", "ahead": 2, "agent_state": "idle", "plan": "0514-x"}]}
        graph = {n["plan"]: n for n in GRAPH["plans"]}
        text = mtm_scan.render_summary(snap, [], [], "", depends=graph)
        self.assertIn("| worktree | not on main | agent | plan | depends on | dependents |", text)
        self.assertIn("| 57 | 1 | idle | 0543-agents | 0514 (38, open) | - |", text)
        self.assertIn("| 38 | 2 | idle | 0514-x | - | 0543 (57, open) |", text)
        plain = mtm_scan.render_summary(snap, [], [], "")  # no graph read: the table stays as it was
        self.assertIn("| worktree | not on main | agent | plan |\n", plain)


if __name__ == "__main__":
    unittest.main()
