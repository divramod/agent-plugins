import time
import unittest

import ci_scan as ci


def iso(ago_s: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(time.time() - ago_s, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run(rid, name, branch, status="completed", conclusion: str | None = "success", ago=60):
    return {"databaseId": rid, "workflowName": name, "headBranch": branch, "status": status,
            "conclusion": conclusion, "createdAt": iso(ago), "url": f"u/{rid}", "headSha": "abcdef123456"}


class Latest(unittest.TestCase):
    def test_the_newest_run_per_workflow_and_branch_of_main_and_slots_only(self):
        runs = [run(1, "ci", "main", conclusion="failure", ago=600), run(2, "ci", "main", ago=60),
                run(3, "ci", "07"), run(4, "ci", "feature-x"), run(5, "lint", "main", ago=30)]
        self.assertEqual(sorted(r["databaseId"] for r in ci.latest_runs(runs, "main")), [2, 3, 5])


class Findings(unittest.TestCase):
    def test_red_main_first_then_stuck_runs_then_red_slots(self):
        latest = [run(1, "ci", "07", conclusion="failure"), run(2, "ci", "main", conclusion="failure"),
                  run(3, "deploy", "main", status="queued", conclusion=None, ago=3600),
                  run(4, "e2e", "main", status="in_progress", conclusion=None, ago=60),
                  run(5, "lint", "main")]
        f = ci.findings(latest, "main", time.time(), set())
        self.assertEqual([(x["kind"], x["run"]) for x in f],
                         [("main-red", 2), ("queued-long", 3), ("slot-red", 1)])

    def test_handled_runs_are_marked(self):
        f = ci.findings([run(2, "ci", "main", conclusion="timed_out")], "main", time.time(), {2})
        self.assertTrue(f[0]["handled"])


class Wake(unittest.TestCase):
    def test_the_oldest_run_queued_over_five_minutes_of_any_branch_wakes(self):
        runs = [run(1, "land", "land/12", status="queued", conclusion=None, ago=400),
                run(2, "land", "land/07", status="queued", conclusion=None, ago=900),
                run(3, "main", "main", status="queued", conclusion=None, ago=60),
                run(4, "main", "main", status="in_progress", conclusion=None, ago=4000)]
        w = ci.waiting(runs, time.time())
        self.assertEqual((w["kind"], w["run"], w["branch"]), ("queued-wake", 2, "land/07"))
        self.assertIsNone(ci.waiting(runs[2:], time.time()))


if __name__ == "__main__":
    unittest.main()
