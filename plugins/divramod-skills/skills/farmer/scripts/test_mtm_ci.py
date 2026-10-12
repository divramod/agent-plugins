import datetime as dt
import unittest

import mtm_ci
import trains


def run(rid, branch, status="completed", conclusion="success", at="2026-10-05T06:00:00Z"):
    return {"databaseId": rid, "headBranch": branch, "headSha": "a" * 40, "status": status,
            "conclusion": conclusion, "createdAt": at, "url": f"https://x/runs/{rid}"}


class MtmCiTest(unittest.TestCase):
    def test_land_runs_become_landing_rows_and_probes_are_left_out(self):
        jobs = {2: [{"name": "linux / rust-test", "conclusion": "failure"},
                    {"name": "park", "conclusion": "failure"}, {"name": "gate", "conclusion": "failure"}]}
        rows = mtm_ci.summary([run(1, "land/07"), run(2, "land/03", conclusion="failure"),
                               run(3, "land/12-probe"), run(4, "land/05", status="in_progress", conclusion=""),
                               run(5, "main")], lambda rid: jobs.get(rid, []), 0)
        self.assertEqual([(r["slot"], r["outcome"], r["task"]) for r in rows],
                         [("07", "landed", ""), ("03", "failed", "linux / rust-test, gate"), ("05", "running", "")])
        self.assertEqual(mtm_ci.running_run(rows, "05")["url"], "https://x/runs/4")

    def test_a_run_is_landed_once_merge_succeeded_whatever_its_ship_jobs_do(self):
        jobs = {1: [{"name": "merge", "conclusion": "success"}, {"name": "ship / deliver", "conclusion": "failure"}],
                2: [{"name": "merge", "conclusion": "success"}, {"name": "ship / publish", "conclusion": None}],
                3: [{"name": "gate", "conclusion": "failure"}, {"name": "ship / deliver", "conclusion": "failure"}]}
        rows = mtm_ci.summary([run(1, "land/07", conclusion="failure"),
                               run(2, "land/03", status="in_progress", conclusion=""),
                               run(3, "land/05", conclusion="failure")], lambda rid: jobs.get(rid, []), 0)
        self.assertEqual([(r["slot"], r["outcome"], r["task"]) for r in rows],
                         [("07", "landed", ""), ("03", "landed", ""), ("05", "failed", "gate")])

    def test_old_runs_are_left_out(self):
        since = dt.datetime(2026, 10, 5, 7, tzinfo=dt.timezone.utc).timestamp()
        self.assertEqual(mtm_ci.summary([run(1, "land/07")], lambda rid: [], since), [])

    def test_ci_mode_asks_for_land_yml_on_the_default_branch(self):
        seen = []
        self.assertTrue(mtm_ci.ci_mode(lambda argv, cwd: seen.append(argv) or "blob\n", "/m", "main"))
        self.assertEqual(seen[0][-1], "origin/main:.github/workflows/land.yml")
        self.assertFalse(mtm_ci.ci_mode(lambda argv, cwd: "", "/m", "main"))

    def test_a_carriers_red_run_after_the_train_wakes_the_farmer(self):
        at = dt.datetime(2026, 10, 5, 8, 0)
        train = {"train:07+03": {"carrier": "07", "passengers": ["03"], "at": at.isoformat()}}
        later = {"slot": "07", "id": "9", "task": "linux / rust-test", "url": "u", "started": at.timestamp() + 60}
        before = dict(later, id="8", started=at.timestamp() - 60)
        self.assertEqual(trains.failures(train, [], [before]), [])
        out = trains.failures(train, [], [before, later])
        self.assertEqual([(a["kind"], a["slot"], a["key"]) for a in out],
                         [("train-failed", "07", "train:07+03:failed:run9")])
        self.assertIn("linux / rust-test", out[0]["text"])


if __name__ == "__main__":
    unittest.main()
