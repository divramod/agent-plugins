"""Plan dependencies in the state (hal2 plan 0595 step 9): the farm's graph from `hal2-cli-plans depends list` becomes
the rows' `depends_on`, `dependents` and `depends_wait`, the columns of the text table and of the farmer's page, and
`waits for 0514 (open)` in the State cell while an open dependency holds the plan's next step. The CLI is a stub (a
function for `src.depends`, or a script on `$HAL2_CLI_PLANS`); never the real farm."""

import os
import stat
import sys
import unittest
from unittest import mock

import state
import state_sources as src
import state_table
import view_farmer
from test_state import Fixture

LINK = {"plan": 514, "slug": "0514-x", "field": "38", "steps": ["2"], "needs": ["3"], "until": "pushed", "state": "open",
        "reached": False}


def graph(**link) -> dict:
    """Plan 0042 (field 02: step 2 is its next) depends on 0514; 0514 has 0042 as its dependent."""
    return {42: {"plan": 42, "slug": "0042-the-answer", "field": "02", "depends_on": [{**LINK, **link}], "dependents": []},
            514: {"plan": 514, "slug": "0514-x", "field": "38", "depends_on": [],
                  "dependents": [{**LINK, "plan": 42, "slug": "0042-the-answer", "field": "02", **link}]}}


class Columns(Fixture):
    def depends(self, found):
        self.mock(src, "depends", lambda *a: found)

    def test_the_row_carries_the_edges_and_the_wait(self):
        self.depends(graph())
        r = self.rows()["02"]
        self.assertEqual(r["next_step"], "2")
        self.assertEqual([l["plan"] for l in r["depends_on"]], [514])
        self.assertEqual(r["dependents"], [])
        self.assertEqual(r["depends_wait"], "waits for 0514 (open)")
        self.assertEqual(self.rows()["10"]["depends_wait"], "")  # no plan, no edge
        self.assertIs(state.collect(str(self.main))["depends_known"], True)

    def test_a_dependency_that_holds_only_a_later_step_or_is_reached_does_not_wait(self):
        for link in ({"steps": ["3"]}, {"reached": True, "state": "pushed"}):
            self.depends(graph(**link))
            self.assertEqual(self.rows()["02"]["depends_wait"], "", link)

    def test_text_table_cells_and_state(self):
        self.depends(graph())
        r = self.rows()["02"]
        cells = state_table.cells(r, "main")
        self.assertEqual(cells[5:], ["0514 (38, open)", ""])
        self.assertIn("waits for 0514 (open)", cells[3])
        out = state_table.table(state.collect(str(self.main)))
        self.assertIn("| 0514 (38, open) |  |", out)

    def test_the_farmer_page_shows_the_columns_and_the_wait(self):
        self.depends(graph())
        rows = view_farmer.fields_of(state.collect(str(self.main)))
        one = next(view_farmer.cells(r, False) for r in rows if r["wt"] == "02")
        self.assertEqual((one["depends_on"], one["dependents"]), ("0514 (38, open)", ""))
        self.assertIn("waits for 0514 (open)", one["state"])
        keys = [c["key"] for c in view_farmer.COLUMNS]
        self.assertEqual(keys[6:8], ["depends_on", "dependents"])
        # the dependency's own row lists the dependent the other way round
        inverse = view_farmer.cells({**view_farmer.DEFAULTS, "wt": "38", "plan": "0514-x", "plan_number": "0514",
                                     "plan_name": "x", "agent": "idle", "dependents": graph()[514]["dependents"]}, False)
        self.assertEqual(inverse["dependents"], "0042 (02, open)")

    def test_no_answer_is_empty_columns_and_one_advisory_line(self):
        self.depends(None)
        data = state.collect(str(self.main))
        self.assertIs(data["depends_known"], False)
        r = {r["wt"]: r for r in data["rows"]}["02"]
        self.assertEqual((r["depends_on"], r["dependents"], r["depends_wait"]), ([], [], ""))
        self.assertIn("plan dependencies: unknown (hal2-cli-plans depends list did not answer)", state_table.line(data))
        self.assertEqual(state_table.line(data).count("plan dependencies"), 1)
        self.assertNotIn("plan dependencies", state_table.line({**data, "depends_known": True}))

    def test_the_cli_end_to_end_over_a_stub(self):
        """`src.depends` against a script that answers like `hal2-cli-plans depends list --all --json`."""
        stub = self.tmp / "cli-stub"
        stub.write_text(f"#!{sys.executable}\nimport json, sys\nassert sys.argv[1:4] == ['depends', 'list', '--all'], sys.argv\n"
                        f"print(json.dumps({{'schema': 1, 'farm': 'proj', 'problems': [], 'plans': {list(graph().values())!r}}}))\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        with mock.patch.dict(os.environ, {"HAL2_CLI_PLANS": str(stub)}):
            got = REAL_DEPENDS(str(self.main))
        self.assertEqual(sorted(got), [42, 514])


REAL_DEPENDS = src.depends


if __name__ == "__main__":
    unittest.main()
