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

    def test_stage_and_code_names_read_as_the_old_ones_did(self):
        jobs = {1: [{"name": "05-xxx1hx/merge", "conclusion": "success"},
                    {"name": "06-lmm1ha/deliver", "conclusion": "failure"}],
                2: [{"name": "05-xxx1hx/merge", "conclusion": "failure"}, {"name": "04-xxx1hx/gate", "conclusion": "failure"},
                    {"name": "06-vhl1hx/docker-publish-github-runner-image", "conclusion": "failure"},
                    {"name": "02-vhl1hx/rust-test", "conclusion": "failure"}, {"name": "mac-host-ship / deliver", "conclusion": "failure"},
                    {"name": "linux-light-ship / x", "conclusion": "failure"}, {"name": "07-lmm1ha/ts-publish-desktop-all", "conclusion": "failure"}]}
        rows = mtm_ci.summary([run(1, "land/07", conclusion="failure"), run(2, "land/03", conclusion="failure")],
                              lambda rid: jobs.get(rid, []), 0)
        self.assertEqual([(r["slot"], r["outcome"], r["task"]) for r in rows],
                         [("07", "landed", ""), ("03", "failed", "04-xxx1hx/gate, 02-vhl1hx/rust-test")])
        self.assertTrue(all(mtm_ci.is_ship(n) for n in ("ship / deliver", "08-lmm1ha/linux-host-ship-start", "x / publish-claude-plugins")))
        self.assertFalse(mtm_ci.is_ship("06-xxx1hx/all-tag-versions"))
        self.assertEqual([mtm_ci.job_part(n) for n in ("merge", "a / merge", "05-xxx1hx/merge", "park")],
                         ["merge", "merge", "merge", "park"])

    def test_old_runs_are_left_out(self):
        since = dt.datetime(2026, 10, 5, 7, tzinfo=dt.timezone.utc).timestamp()
        self.assertEqual(mtm_ci.summary([run(1, "land/07")], lambda rid: [], since), [])

    def test_ci_mode_asks_for_both_workflow_files_on_the_default_branch(self):
        seen = []
        self.assertFalse(mtm_ci.ci_mode(lambda argv, cwd: seen.append(argv) or "", "/m", "main"))  # neither
        self.assertEqual([argv[-1] for argv in seen], ["origin/main:.github/workflows/merge-to-main.yml",
                                                       "origin/main:.github/workflows/land.yml"])
        self.assertEqual(seen[0][:3], ["git", "cat-file", "-t"])
        self.assertTrue(mtm_ci.ci_mode(lambda argv, cwd: "blob\n", "/m", "main"))  # both

    def test_ci_mode_accepts_either_workflow_file(self):
        only_old = lambda argv, cwd: "blob\n" if argv[-1].endswith("/land.yml") else ""
        only_new = lambda argv, cwd: "blob\n" if argv[-1].endswith("/merge-to-main.yml") else ""
        other = lambda argv, cwd: "blob\n" if argv[-1].endswith("/ci.yml") else ""
        self.assertTrue(mtm_ci.ci_mode(only_old, "/m", "main"))
        self.assertTrue(mtm_ci.ci_mode(only_new, "/m", "main"))
        self.assertFalse(mtm_ci.ci_mode(other, "/m", "main"))

    def test_runs_of_both_workflow_files_are_joined_newest_first(self):
        answers = {"merge-to-main.yml": [run(4, "land/08", status="queued", conclusion="", at="2026-10-12T07:00:00Z"),
                                         run(2, "land/07", at="2026-10-12T06:00:00Z")],
                   "land.yml": [run(3, "land/05", at="2026-10-12T06:30:00Z"),
                                run(1, "land/03", status="in_progress", conclusion="", at="2026-10-11T06:00:00Z")]}
        asked = []
        both = lambda args, cwd: asked.append(args) or answers[args[args.index("--workflow") + 1]]
        self.assertEqual([r["databaseId"] for r in mtm_ci.runs_of(both, "/m")], [4, 3, 2, 1])
        self.assertEqual([a[a.index("--workflow") + 1] for a in asked], ["merge-to-main.yml", "land.yml"])
        self.assertEqual(asked[0][:3] + asked[0][5:7], ["gh", "run", "list", "--limit", "100"])
        self.assertEqual(mtm_ci.unfinished(both, "/m"), 2)  # one unfinished run of each file
        rows = mtm_ci.landings(lambda args, cwd: answers[args[args.index("--workflow") + 1]]
                               if args[:3] == ["gh", "run", "list"] else {"jobs": []}, "/m", 0)
        self.assertEqual([(r["slot"], r["outcome"]) for r in rows],
                         [("08", "running"), ("05", "landed"), ("07", "landed"), ("03", "running")])

    def test_a_workflow_file_github_does_not_know_has_no_runs(self):
        old = [run(1, "land/03", status="in_progress", conclusion="", at="2026-10-11T06:00:00Z")]
        new = [run(2, "land/07", status="queued", conclusion="", at="2026-10-12T06:00:00Z"), run(3, "land/05")]
        before = lambda args, cwd: old if "land.yml" in args else None  # the rename has not landed
        after = lambda args, cwd: new if "merge-to-main.yml" in args else None  # land.yml is gone
        self.assertEqual((mtm_ci.unfinished(before, "/m"), [r["databaseId"] for r in mtm_ci.runs_of(before, "/m")]),
                         (1, [1]))
        self.assertEqual((mtm_ci.unfinished(after, "/m"), [r["databaseId"] for r in mtm_ci.runs_of(after, "/m")]),
                         (1, [2, 3]))
        self.assertEqual((mtm_ci.unfinished(lambda args, cwd: None, "/m"), mtm_ci.runs_of(lambda args, cwd: None, "/m")),
                         (0, []))

    def test_a_run_listed_under_both_names_counts_once(self):
        same = [run(1, "land/03", status="in_progress", conclusion="")]
        self.assertEqual(mtm_ci.unfinished(lambda args, cwd: same, "/m"), 1)
        self.assertEqual(len(mtm_ci.landings(lambda args, cwd: same if args[2] == "list" else {"jobs": []}, "/m", 0)), 1)

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
