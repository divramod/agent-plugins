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


class Stuck(unittest.TestCase):
    def test_a_long_run_its_own_fail_fast_is_ending_says_so_and_is_never_cancelled_by_hand(self):
        def job(conclusion, stop, status="completed"):
            return {"name": "02-vhl1ha/python-test", "conclusion": conclusion, "steps": [
                {"name": "[07] gate python-test", "conclusion": "failure", "status": "completed"},
                {"name": "[20] fail fast: stop the run", "conclusion": stop, "status": status}]}
        long = lambda: {"run": 7, "kind": "running-long", "why": "land running 95 min on 08"}
        asking = ci.stuck(long(), [job("", "", "in_progress")])  # the stop step runs: its request is on its way
        self.assertTrue(asking["ending"])
        self.assertEqual(asking["why"], "land running 95 min on 08: its own fail fast is ending it, never cancel it")
        self.assertTrue(ci.stuck(long(), [job("cancelled", "skipped")])["ending"])  # a gate job cut with its run
        hung = ci.stuck(long(), [job("", "", "pending")])  # a failed step, the stop step still to come: a hang
        self.assertEqual((hung["ending"], hung["why"]), (False, "land running 95 min on 08"))
        self.assertFalse(ci.stuck(long(), [job("", "failure")])["ending"])  # refused: nothing stops the run
        self.assertFalse(ci.stuck(long(), [])["ending"])  # no jobs read: as before

    def test_a_failed_jobs_hand_off_and_its_stop_job_are_ending_and_a_refused_cancel_is_not(self):
        # Plan 0319: `bash-lint` failed and handed off; `fail-fast-a` sends the request in its step.
        def gate(stop):
            return {"name": "03-x-host-x/bash-lint", "conclusion": "failure", "steps": [
                {"name": "[07] gate bash-lint", "conclusion": "failure", "status": "completed"},
                {"name": "[21] fail fast: stop the run", "conclusion": stop, "status": "completed"}]}

        def stopper(conclusion, status="completed"):
            return {"name": "03-x-host-x/fail-fast-a", "conclusion": "", "steps": [
                {"name": "[02] fail fast: cancel the run", "conclusion": conclusion, "status": status}]}
        long = lambda: {"run": 7, "kind": "running-long", "why": "land running 95 min on 08"}
        for jobs in ([gate("success")], [gate("success"), stopper("", "in_progress")],
                     [gate("success"), stopper("success")]):
            self.assertTrue(ci.stuck(long(), jobs)["ending"])
        self.assertFalse(ci.stuck(long(), [gate("success"), stopper("failure")])["ending"])  # refused: cancel it


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
