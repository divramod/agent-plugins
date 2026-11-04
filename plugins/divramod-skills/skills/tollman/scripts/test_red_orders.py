"""Each red job of a land run has its fix order or a named reason (red_orders.py, the user 2026-11-04): read against
GitHub's own job list, never the triage; a job nobody was told of is MISSING (exit 1), an unreadable run exit 3."""
# enforces .adr/tollman.md

import unittest
from unittest import mock

import red_orders

RID = "41824763199"
URL = f"https://github.com/divramod/hal2/actions/runs/{RID}"


def job(name, conclusion="failure", status="completed"):
    return {"name": name, "conclusion": conclusion, "status": status, "steps": []}


class Check(unittest.TestCase):
    def setUp(self):
        self.rows = [{"kind": "formed", "train": "T", "cars": []}, {"kind": "run", "train": "T", "run": URL}]
        self.entry = {}
        p = mock.patch.object(red_orders.train_state, "lines", lambda main: list(self.rows))
        p.start()
        self.addCleanup(p.stop)

    def check(self, jobs):
        return red_orders.check("/m", read=lambda rid: jobs, entries=lambda rid: self.entry)

    def test_an_ordered_job_names_field_id_and_state(self):
        self.rows += [{"kind": "order", "field": "47", "id": "47-fix-3", "run": URL, "jobs": ["rust-release-linux"]},
                      {"kind": "fixed", "field": "47", "id": "47-fix-3", "sha": "6b1645c3fe00"}]
        r = self.check([job("c2-01-rust-release-linux"), job("gate"), job("c2-02-lint", "success")])
        self.assertEqual(r["missing"], 0)
        self.assertEqual([v["job"] for v in r["runs"][0]["reds"]], ["c2-01-rust-release-linux"])
        self.assertEqual(r["runs"][0]["reds"][0]["orders"], [{"id": "47-fix-3", "field": "47",
                                                              "state": "fixed 6b1645c3fe"}])
        self.assertEqual(red_orders.exit_code(r), 0)

    def test_an_also_line_and_a_why_name_count(self):
        self.rows += [{"kind": "order", "field": "47", "id": "47-fix-3", "run": RID, "jobs": ["x"],
                       "why": "c2-06-python-build-test-linux: y"},
                      {"kind": "order", "field": "55", "id": "55-fix-4", "also": "55-fix-4", "run": URL,
                       "jobs": ["bash-build-test-mac"]}]
        r = self.check([job("c2-06-python-build-test-linux"), job("c4-01-bash-build-test-mac")])
        self.assertEqual([v["orders"][0]["field"] for v in r["runs"][0]["reds"]], ["47", "55"])

    def test_a_job_nobody_was_told_of_is_missing(self):
        self.rows.append({"kind": "order", "field": "47", "id": "47-fix-3", "run": "1", "jobs": ["lint"]})
        r = self.check([job("c2-02-lint")])
        self.assertEqual((r["missing"], red_orders.exit_code(r)), (1, 1))
        self.assertIn("MISSING", "\n".join(red_orders.lines(r)))

    def test_reasons_and_quiet_triage_cover(self):
        self.entry = {"job_reasons": {"lint": "the barn's red"},
                      "reds": [{"kind": "runner", "job": "c4-01-bash-build-test-mac"}]}
        r = self.check([job("c2-02-lint"), job("c4-01-bash-build-test-mac", "timed_out")])
        self.assertEqual([v["verdict"] for v in r["runs"][0]["reds"]], ["reason", "reason"])

    def test_an_unreadable_run_is_never_green(self):
        r = red_orders.check("/m", read=lambda rid: None, entries=lambda rid: {})
        self.assertEqual(red_orders.exit_code(r), 3)
        self.assertIn("UNREADABLE", red_orders.lines(r)[0])

    def test_no_train_checks_the_last_landed_run(self):
        self.rows = [{"kind": "formed", "train": "A", "cars": []}, {"kind": "landed", "train": "A", "run": URL}]
        self.assertEqual(red_orders.runs(self.rows, []), [RID])
        self.assertEqual(red_orders.runs(self.rows, [URL, RID]), [RID])

    def test_report_never_raises(self):
        with mock.patch.object(red_orders, "check", side_effect=RuntimeError("boom")), \
                mock.patch.object(red_orders.mtm_scan, "main_checkout", lambda repo: repo):
            self.assertEqual(red_orders.report("/m"), 3)


if __name__ == "__main__":
    unittest.main()
