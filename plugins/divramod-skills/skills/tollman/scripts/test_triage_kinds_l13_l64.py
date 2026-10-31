"""Hal2 plan 0490 step 10: the triage kinds of learnings L13, L64 and L134, in both triages (triage.py for a train's
landing, run_triage.py for a finished land run).

- L64 (2026-10-20 17:15Z): train 9's job a1-01-ci-route never got a runner (hz01 parked), was cancelled after 11 min
  with no log, and early_order.py ordered car 55 for it. A red job gh gives no step is a runner fault.
- L13 (2026-10-15): train 10+06+01+17+22 went red in stack-test only on AgentsRemoteOpen (p95 57.7 ms against 51 ms)
  and ViewSwitchFrame: a budget missed on the shared host is a load flake, never a car's; twice, the flaky brief.
- L134 (= L97, row 16): GitHub skips the other landing workflow's run on the same branch; the barn's-red check never
  takes such a run for "the other worktree's run".
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import run_triage
import run_triage_act
import run_triage_read as read
import triage
from gh_fake import job, run
from test_watch_skipped import PerWorkflow

UNSERVED = {"name": "a1-01-ci-route", "status": "completed", "conclusion": "cancelled", "steps": []}
STEP = "[03] gate stack-test desktop-e2e"
JOB = "d1-01-stack-test"
BUDGET_LOG = "\n".join(f"{JOB}\t{STEP}\t2026-10-15T03:10:00.1Z {t}" for t in (
    "✘  3 [electron] › agents.spec.ts:320:7 › agents › remote open within its budget",
    "Error: AgentsRemoteOpen: n=20 p50=41.0 p95=57.7 ms, budget 51 ms",
    "##[error]Process completed with exit code 1."))
REAL_LOG = BUDGET_LOG + f"\n{JOB}\t{STEP}\tError: expect(locator).toBeVisible() failed: the remote list is empty"
STACK = {"name": JOB, "status": "completed", "conclusion": "failure",
         "steps": [{"name": "checkout", "conclusion": "success"}, {"name": STEP, "conclusion": "failure"}]}
RUN = {"id": "41", "url": "https://github.com/x/actions/runs/41", "sha": "a" * 40}


class Triage(unittest.TestCase):
    """triage.classify: a train's red landing (train_red.py, early_order.py)."""

    def test_l64_a_job_no_runner_served_is_a_runner_fault_never_a_car_s(self):
        v = triage.classify({"id": "9"}, [UNSERVED], "", {"cars": [{"field": "55", "files": ["a.txt"]}]})
        self.assertEqual((v["kind"], v["evidence"]["match"]), ("runner", "no runner served a1-01-ci-route"))
        served = dict(UNSERVED, steps=[{"name": "set up job", "conclusion": "cancelled"}])
        self.assertEqual(triage.classify({"id": "9"}, [served], "", {})["kind"], "car", "it ran: judged as before")
        self.assertEqual(triage.classify({"id": "9"}, [{"name": "x"}], "", {})["kind"], "car",
                         "a job read without its steps is never taken for unserved")

    def test_l13_a_budget_only_red_is_one_fresh_run_a_real_failure_stays_a_car_s(self):
        v = triage.classify({"id": "1"}, [STACK], BUDGET_LOG, {})
        self.assertEqual((v["kind"], v["evidence"]["budget"]), ("runner", True))
        self.assertIn("p95=57.7 ms, budget 51 ms", v["evidence"]["match"])
        self.assertEqual(triage.classify({"id": "1"}, [STACK], REAL_LOG, {})["kind"], "car")
        rust = "FAIL CrmSearch: p50 3.0 ms, p95 9.1 ms (budget 8 ms), max 12.0 ms, n 50\nover budget: [\"CrmSearch\"]"
        self.assertEqual(triage.classify({"id": "1"}, [STACK], rust, {})["kind"], "runner", "hal2-core's wording")
        built = "phase build: failed after 900s (exit 124)\nTest timeout of 30000ms exceeded."
        self.assertEqual(triage.classify({"id": "1"}, [STACK], built, {})["kind"], "car", "a build phase: D13's")

    def test_l134_the_other_run_is_never_a_skipped_companion(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        Path(home.name, ".hal").mkdir()
        Path(home.name, ".hal", "landing.toml").write_text('workflow = "cloud"\n')
        skipped = run(591, "land/05", "2026-10-17T09:41:00Z", conclusion="skipped")  # newest, the local file's
        local = run(592, "land/05", "2026-10-17T09:42:00Z", conclusion="failure")  # newer still, not the setting's
        cloud = run(590, "land/05", "2026-10-17T09:40:00Z", sha="c" * 40)
        gh = PerWorkflow({"merge-to-main-local.yml": [local, skipped], "merge-to-main-cloud.yml": [cloud]}).start(self)
        gh.jobs = {"590": [job("d1-01-rust-test")], "591": [], "592": [job("d1-01-rust-test")]}
        train = {"at": "2026-10-17T10:00:00Z", "carrier": "tollman-hal2"}
        with mock.patch.dict(os.environ, {"HAL2_LAND_WORKFLOW": ""}):
            other = triage.other_run(home.name, train, lambda rid: gh.jobs.get(str(rid), []))
            self.assertEqual((other["url"], other["red"]), (cloud["url"], ["d1-01-rust-test"]))
            gh.by_file = {"merge-to-main-local.yml": [skipped], "merge-to-main-cloud.yml": []}
            self.assertIsNone(triage.other_run(home.name, train, lambda rid: []), "a lone skipped run: none")


class RunTriage(unittest.TestCase):
    """run_triage.triage: a finished land run, every red unit."""

    def test_l64_an_unserved_job_is_runner_and_the_recheck_agrees(self):
        (v,) = run_triage.triage(RUN, [UNSERVED], "", {})["verdicts"]
        self.assertEqual((v["kind"], v["recheck"], v["owner"]), ("runner", "agrees", None))
        self.assertTrue(v["evidence"]["unserved"])

    def test_l13_a_budget_miss_is_a_flake_and_twice_the_flaky_brief(self):
        (v,) = run_triage.triage(RUN, [STACK], BUDGET_LOG, {})["verdicts"]
        self.assertEqual((v["kind"], v["recheck"], v["evidence"]["budget"], v["owner"]), ("flake", "agrees", True, None))
        self.assertTrue(any("budget 51 ms" in t for t in v["evidence"]["lines"]), v["evidence"]["lines"])
        train = {"train": "t10", "carrier": "tollman-train-0360"}
        once = run_triage_act.actions("/x/tollman-hal2", "/x", run_triage.triage(RUN, [STACK], BUDGET_LOG, {}), train)
        self.assertEqual([a["kind"] for a in once], ["triage-record"], "the first miss: nobody")
        previous = [{"id": "40", "units": read.signatures([STACK], BUDGET_LOG)}]
        twice = run_triage.triage(RUN, [STACK], BUDGET_LOG, {"previous": previous})
        self.assertEqual((twice["verdicts"][0]["kind"], twice["verdicts"][0]["evidence"]["repeat_of"]), ("flake", "40"))
        acts = run_triage_act.actions("/x/tollman-hal2", "/x", twice, train)
        self.assertEqual([a["kind"] for a in acts], ["triage-record", "triage-flaky"])
        argv = acts[1]["argv"]
        self.assertEqual((Path(argv[1]).name, argv[2], argv[argv.index("--slot") + 1]),
                         ("flaky_brief.py", "place", "tollman-train-0360"))

    def test_l13_a_real_failure_beside_a_budget_line_is_no_flake(self):
        kinds = {v["kind"] for v in run_triage.triage(RUN, [STACK], REAL_LOG, {})["verdicts"]}
        self.assertNotIn("flake", kinds)
        self.assertFalse(read.budget_only(["phase build: failed after 900s (exit 124)"]))


if __name__ == "__main__":
    unittest.main()
