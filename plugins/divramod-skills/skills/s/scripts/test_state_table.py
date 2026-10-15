"""state_table.py: the cells, the table and the line under it (hal2 plan 0268 step 2). Pure, no fixtures needed."""

import unittest

import state_table as t


def row(**kw) -> dict:
    base = {"wt": "00", "is_main": False, "plan": "", "plan_number": None, "plan_name": None, "steps_done": None,
            "steps_total": None, "agent": None, "uncommitted": None, "ahead": None, "last_commit_age": None,
            "queue": None, "ci": [], "waits": []}
    return {**base, **kw}


class CellsTest(unittest.TestCase):
    def test_age(self):
        self.assertEqual([t.age(s) for s in (None, 0, 300, 3 * 3600 + 5, 2 * 86400)], ["", "0m", "5m", "3h", "2d"])

    def test_wt_cell_marks(self):
        self.assertEqual([t.wt_cell(row(wt="01", own=own), nested) for own, nested in
                          ((False, False), (True, False), (False, True), (True, True))],
                         ["01", "**01**", "↳ 01", "↳ **01**"])
        self.assertEqual(t.cells(row(wt="31"), "main", True)[0], "↳ 31")

    def test_plan_and_steps(self):
        r = row(plan="0253-mobile-app", plan_number="0253", plan_name="mobile-app", steps_done=28, steps_total=36)
        self.assertEqual(t.cells(r, "main")[:3], ["00", "0253 mobile app", "28 of 36"])
        self.assertEqual(t.cells(row(plan="shots/3/fix-x"), "main")[1:3], ["shots/3/fix-x", ""])
        self.assertEqual(t.cells(row(), "main")[1:3], ["free", ""])

    def test_state_phrases_in_fixed_order(self):
        r = row(agent="busy", queue={"holds": True, "position": 1, "state": "x"}, uncommitted=2, ahead=3, last_commit_age=7200,
                ci=[{"workflow": "merge-to-main", "status": "in_progress", "branch": "land/00"},
                    {"workflow": "ci", "status": "queued", "branch": "00"}])
        self.assertEqual(t.state_cell(r, "main"),
                         "busy; holds the merge queue; check run queued; land run running; 2 uncommitted; 3 not on main; last commit 2h")
        self.assertEqual(t.state_cell(row(agent="none", queue={"holds": False, "position": 2, "state": "x"}), "main"),
                         "no session; waits in the queue at 2")
        self.assertEqual(t.state_cell(row(is_main=True, ahead=1), "main"), "1 not pushed")
        self.assertEqual(t.state_cell(row(), "main"), "")  # nothing known, nothing said

    def test_a_run_of_the_landing_workflow_under_any_name_is_a_land_run(self):
        for name in ("dev-merge-to-main", "merge-to-main", "land"):  # plan 0349 D52's name, the ones before it
            self.assertEqual(t.run_phrase({"workflow": name, "status": "in_progress", "branch": "07"}), "land run running")
        self.assertEqual(t.run_phrase({"workflow": "local-macos-26-macbook-18.4", "status": "queued", "branch": "07"}),
                         "check run queued")

    def test_waits(self):
        r = row(waits=[{"kind": "queue"}, {"kind": "ci"}, {"kind": "ask"}, {"kind": "unacked", "ids": ["a1", "a2"]},
                       {"kind": "questions", "open": ["Q31", "Q32"]}])
        self.assertEqual(t.waits_cell(r), "the queue; the run; the farmer's answer; ack a1; ack a2; Q31; Q32")
        held = row(waits=[{"kind": "queue", "holds": True, "position": 0}, {"kind": "ci"}])
        self.assertEqual(t.waits_cell(held), "the run")  # the holder of the queue does not wait for it
        self.assertEqual(t.waits_cell(row(waits=[{"kind": "queue", "holds": False, "position": 2}])), "the queue")
        self.assertEqual(t.waits_cell(row()), "")

    def test_question_ranges(self):
        self.assertEqual(t.ranges(["Q5", "Q6", "Q7", "Q8", "Q15"]), ["Q5-Q8", "Q15"])
        self.assertEqual(t.ranges(["Q19", "Q20", "Q22", "Q24", "Q25", "Q26"]), ["Q19", "Q20", "Q22", "Q24-Q26"])
        self.assertEqual(t.ranges(["Q9"]), ["Q9"])


class TableTest(unittest.TestCase):
    def data(self, **kw) -> dict:
        d = {"default": "main", "head": "abcd1234", "head_age": 300, "head_subject": "x" * 70,
             "queue": [{"slot": "05", "holding": True, "position": 1}, {"slot": "07", "holding": False, "position": 3},
                       {"slot": "06", "holding": False, "position": 2}],
             "runs": [{}, {}], "rows": [row(wt="05", ci=[{"workflow": "ci", "status": "queued", "branch": "05"}]), row(wt="06")]}
        return {**d, **kw}

    def test_table_and_line(self):
        lines = t.table(self.data()).split("\n")
        self.assertEqual(lines[:2], ["| WT | Plan | Steps | State | Waits for |", "|---|---|---|---|---|"])
        self.assertEqual(lines[2], "| 05 | free |  | check run queued |  |")
        self.assertEqual(lines[4], "")
        self.assertEqual(lines[5], "main: abcd1234 5m ago " + "x" * 59 + "…; queue: 05 holds; waiting: 06, 07; open CI runs: 2 (05)")

    def test_line_unknowns_and_empty(self):
        self.assertEqual(t.line(self.data(queue=[], runs=[], head_age=None, head_subject="s")), "main: abcd1234 s; queue: empty; open CI runs: none")
        self.assertEqual(t.line(self.data(queue=None, runs=None, head=None)), "main")

    def test_pipe_escaped(self):
        self.assertIn("a\\|b", t.table(self.data(rows=[row(plan="a|b")])))


if __name__ == "__main__":
    unittest.main()
