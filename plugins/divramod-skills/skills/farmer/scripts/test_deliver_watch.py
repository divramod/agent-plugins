"""The Mac install's finding (deliver_watch.py, hal2 plan 0755 D30): a red or cancelled `f3-01-install-mac` of the newest
land run with a green merge wakes and pushes once per sha; a green, running or absent one is no finding. A fake gh
(`run_json`) and a scratch main checkout; never the real gh, alarm or notice."""

import datetime as dt
import json
import unittest
from unittest import mock

import deliver_watch as dw
import duties
import mtm_ci
import tick

NOW = dt.datetime(2026, 11, 8, 12, 0)
SHA = "abcdef0123456789"


def job(name, conclusion, steps=()):
    return {"name": name, "conclusion": conclusion, "steps": [{"name": s, "conclusion": c} for s, c in steps]}


def jobs(install="success", merge="success", steps=()):
    out = [job("d2-01-git-merge", merge)]
    if install is not None:
        out.append(job("f3-01-install-mac", install, steps))
    return out


class Gh:
    """A fake `run_json`: the runs list (newest first) and each run's jobs."""

    def __init__(self, runs):
        self.runs, self.asked = runs, []

    def __call__(self, args, cwd=None):
        self.asked.append(args)
        if args[:2] == ["gh", "api"]:
            return [{"id": r["id"], "path": ".github/workflows/merge-to-main-cloud.yml", "head_branch": r.get("branch", "land/07"),
                     "head_sha": r.get("sha", SHA), "status": r.get("status", "completed"), "conclusion": "success",
                     "created_at": f"2026-11-08T11:{59 - i:02d}:00Z", "html_url": f"https://x/runs/{r['id']}", "event": "push",
                     "display_title": ""} for i, r in enumerate(self.runs)]
        rid = int(args[3])
        return {"jobs": next(r["jobs"] for r in self.runs if r["id"] == rid)}


class Watch(unittest.TestCase):
    def plan(self, runs):
        self.gh = Gh(runs)
        with mock.patch.object(mtm_ci, "live_land_names", return_value=["merge-to-main-cloud.yml"]):
            return dw.plan({"main": "/x/hal2"}, self.gh)

    def test_a_green_skipped_running_or_absent_install_is_no_finding(self):
        for install in ("success", "skipped", None, "neutral"):
            self.assertEqual(self.plan([{"id": 1, "jobs": jobs(install)}]), [], install)
        self.assertEqual(self.plan([{"id": 1, "jobs": jobs(install=None)}]), [])

    def test_graph_0_0_3s_name_and_past_runs_are_the_install_job(self):
        # Plan 0755 D46: `f3-01-macos-install`; a past run keeps `f3-01-install-mac` (deliver_watch.JOBS).
        self.assertEqual(dw.JOBS, {"macos-install", "install-mac"})
        self.assertEqual(mtm_ci.job_part("f3-01-macos-install"), "macos-install")

    def test_a_red_install_wakes_and_pushes_once_per_sha(self):
        acts = self.plan([{"id": 7, "jobs": jobs("failure", steps=[("deploy: sign", "success"), ("deploy: install", "failure")])}])
        self.assertEqual([(a["duty"], a["kind"], a["do"]) for a in acts], [("delivery", "red", "wake"), ("delivery", "alarm", "run")])
        self.assertIn("install f3-01-install-mac of abcdef0123 is red: deploy: install, run https://x/runs/7", acts[0]["text"])
        self.assertEqual(acts[0]["evidence"]["failed"], ["deploy: install"])
        argv = acts[1]["argv"]
        self.assertEqual((argv[2], argv[-2:]), ("deliver-red", ["--repo", "/x/hal2"]))
        self.assertNotIn("deliver-red", __import__("alarm").STUCK, "a push, no ring")
        log = [{"at": "2026-11-08T11:59:00Z", "key": a["key"]} for a in acts]
        self.assertEqual(tick.fresh(acts, log, NOW), [], "the farmer's log remembers the keys")
        later = self.plan([{"id": 8, "sha": "1111111111111111", "jobs": jobs("timed_out")}])
        self.assertEqual(len(tick.fresh(later, log, NOW)), 2, "the next red sha reaches the user again")

    def test_a_cancelled_install_after_a_green_merge_is_stuck(self):
        acts = self.plan([{"id": 7, "jobs": jobs("cancelled")}])
        self.assertEqual([(a["kind"], a["key"]) for a in acts], [("stuck", f"deliver-stuck:{SHA}"), ("alarm", f"deliver-alarm:{SHA}")])
        self.assertIn("never started", acts[0]["text"])

    def test_the_newest_run_with_a_green_merge_decides(self):
        runs = [{"id": 9, "status": "in_progress", "jobs": jobs("failure", merge="in_progress")},
                {"id": 8, "jobs": jobs("success")}, {"id": 7, "jobs": jobs("failure")}]
        self.assertEqual(self.plan(runs), [], "run 9 has not merged; run 8 is green; run 7 is older")
        self.assertEqual(self.plan([{"id": 9, "jobs": jobs("failure", merge="failure")}]), [], "no green merge: no verdict")

    def test_only_land_branches_count(self):
        self.assertEqual(self.plan([{"id": 1, "branch": "main", "jobs": jobs("failure")}]), [])

    def test_nothing_to_read_is_no_finding(self):
        self.assertEqual(dw.plan({}), [])
        with mock.patch.object(mtm_ci, "live_land_names", return_value=[]):
            self.assertEqual(dw.plan({"main": "/x/hal2"}, Gh([])), [])
        with mock.patch.object(mtm_ci, "live_land_names", return_value=["merge-to-main-cloud.yml"]):
            self.assertEqual(dw.plan({"main": "/x/hal2"}, lambda a, c=None: None), [])

    def test_the_ci_duty_adds_it_after_its_own_findings(self):
        acts = duties.plan_ci({}, {"top": "/x/farmer", "main": "/x/hal2"}, {"findings": []},
                              delivery=self.plan([{"id": 7, "jobs": jobs("failure")}]))
        self.assertEqual([a["kind"] for a in acts], ["red", "alarm"])


if __name__ == "__main__":
    unittest.main()
