"""Hal2 plan 0490 step 25 (D25, open-train-brief.md point 5): a red step of a job that still runs is acted on at once.

- the read: one jobs list a pass while a job runs (once per round), none when nothing runs (D9)
- a running job with a red step: one `step failed: <job> <step>` line and one acked order in the same pass; before
  the merge to the current train (no `--post`), after it to the next (`--post <train>`); the next pass: nothing
- the job's end with the same red orders nothing new (early_order sees the order) and rechecks it from the log
- a runner step's red names `runner` and orders nobody; a repeat or a step red within seconds orders nobody
"""
# enforces .adr/deterministic-first.md and .adr/tollman.md

import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import ci_health
import gh_runs
import minute
import run_triage_step as step
import run_triage_step_read as reads
import run_triage_wire as wire
import step_red
import train_state
import watch_events
from gh_fake import FakeGh, run
from test_run_triage_wire import Folder

RID, NAME, BRANCH = "777", "02+09@2026-10-30T13:00:00Z", "land/train-25-1"
URL = f"https://github.com/x/actions/runs/{RID}"
STACK, MERGE = "d1-01-stack-test", "d2-01-git-merge"
RED = "[06] gate stack-test hub-e2e"
CARS = [{"field": "02", "branch": "02", "head": "2" * 40, "plan": "0401-hub-login"},
        {"field": "09", "branch": "09", "head": "9" * 40, "plan": "0402-other"}]
FILES = [{"field": "02", "files": ["code/typescript/apps/hub-e2e/tests/login.spec.ts"]},
         {"field": "09", "files": ["code/rust/libs/x/src/lib.rs"]}]
LOG = (f"{STACK}\t{RED}\t2026-10-30T13:16:39Z ##[error] login failed in "
       "code/typescript/apps/hub-e2e/tests/login.spec.ts\n")


def api_step(name, conclusion, start="2026-10-30T13:10:00Z", end="2026-10-30T13:16:40Z"):
    return {"name": name, "status": "completed" if conclusion else "in_progress", "conclusion": conclusion,
            "started_at": start, "completed_at": end if conclusion else None}


def api_job(red=RED, runner="hz01-host-a", status="in_progress", end="2026-10-30T13:16:40Z"):
    steps = [api_step("Set up job", "success"), api_step(red, "failure", end=end),
             api_step("[13] gate stack-test desktop-e2e", None if status == "in_progress" else "success")]
    return {"id": 9001, "name": STACK, "status": status, "conclusion": None if status == "in_progress" else "failure",
            "runner_name": runner, "steps": steps}


def view(api: dict) -> dict:
    """The run view's form of an API job (`gh run view --json jobs`)."""
    return {"name": api["name"], "status": api["status"], "conclusion": api["conclusion"],
            "steps": [{"name": s["name"], "conclusion": s["conclusion"]} for s in api["steps"]]}


MERGED = {"id": 9002, "name": MERGE, "status": "completed", "conclusion": "success", "completed_at":
          "2026-10-30T13:12:00Z", "steps": []}


class Watch(Folder):
    def setUp(self):
        super().setUp()
        self.gh = FakeGh([run(RID, BRANCH, "2026-10-30T13:00:00Z", status="in_progress")]).start(self)
        main = str(self.main)
        train_state.append(main, "formed", "tollman-hal2", train=NAME, cars=CARS, base="b" * 40)
        started = train_state.append(main, "started", "tollman-hal2", train=NAME, pid=4711, land_ref=BRANCH)["at"]
        tgt = {"run": RID, "url": URL, "train": NAME, "started": started, "seen": [], "closed": False, "base": {}}
        self.panes = {"02": "%2", "09": "%9"}
        for p in (mock.patch.object(watch_events, "target", lambda m, rows, s: s if s.get("run") else dict(tgt)),
                  mock.patch.object(minute, "next_train", lambda *a, **kw: []),
                  mock.patch.object(ci_health, "check", lambda *a, **kw: []),
                  mock.patch.object(reads, "round_context", lambda top, m: {"panes": self.panes, "log": []}),
                  mock.patch.object(reads, "context", self.context)):
            p.start()
            self.addCleanup(p.stop)

    def context(self, top, main, train, ctx, standing, doc):
        return {"cars": FILES, "yard": [], "live": set(ctx["panes"]), "previous": self.previous(), "gate_jobs": set(),
                "pipeline_field": None, "base": train.get("base"), "moved": {},
                "dedup": {"orders": [], "wagons": [], "plans": {}}}

    def previous(self):
        return []

    def set_jobs(self, *api):
        self.gh.api_jobs[RID] = list(api)
        self.gh.jobs[RID] = [view(j) for j in api]

    def tick(self):
        with gh_runs.round(None):
            return minute.events(str(self.top), str(self.main), False, {"queue": []}, self.panes)

    def orders(self, planned):
        return [a for a in planned if a["kind"] in ("triage-order", "early-order", "post-order", "train-red")]


class RedStep(Watch):
    def test_one_line_and_one_order_to_the_current_train_then_nothing(self):
        self.set_jobs(api_job())
        planned = self.tick()
        lines = [a["text"] for a in planned if a["duty"] == "watch"]
        self.assertEqual(lines, [f"step failed: {STACK} {RED}"])
        (order,) = self.orders(planned)
        argv = order["argv"]
        self.assertEqual((order["do"], order["slot"], order["key"]), ("run", "02", f"triage:{RID}:stack-test"))
        self.assertEqual(argv[2:4] + argv[-4:], ["order", "02", "--run", URL, "--repo", str(self.top)])
        self.assertNotIn("--post", argv, "before the merge: fixed in place in the current train")
        self.assertTrue(argv[argv.index("--why") + 1].startswith(f"{STACK}: step {RED} red while the job runs"))
        self.assertEqual(self.tick(), [], "the next pass: the step is told, nothing new")
        (kept,) = wire.state(str(self.main))["runs"][0]["steps"]
        self.assertEqual((kept["owner"], kept["target"], kept["ordered"]), ("02", "current", True))

    def test_after_the_merge_the_fix_rides_the_next_train(self):
        self.set_jobs(MERGED, api_job())
        (order,) = self.orders(self.tick())
        argv = order["argv"]
        self.assertEqual(argv[argv.index("--post") + 1], NAME, "--post: rides the train standing next")
        self.assertEqual(order["key"], f"triage:{RID}:stack-test", "the key the run's triage gives the job's red")

    def test_the_job_s_end_orders_nothing_new_and_rechecks_from_the_log(self):
        self.set_jobs(api_job())
        (order,) = self.orders(self.tick())
        why = order["argv"][order["argv"].index("--why") + 1]
        train_state.append(str(self.main), "order", "tollman-hal2", train=NAME, field="02", branch="02-train-fix",
                           base="b" * 40, why=why, run=URL, id="02-fix-1")  # what orders.py writes when it runs
        self.gh.logs["--job"] = LOG  # `gh run view --job 9001 --log-failed`: the fake keys it by args[3]
        self.set_jobs(api_job(status="completed"))
        planned = self.tick()
        self.assertEqual([a["text"] for a in planned if a["duty"] == "watch"][0][:12], "job failed: ")
        self.assertEqual(self.orders(planned), [], "early_order sees the step's order: no second one")
        (check,) = [a for a in planned if a["key"].endswith(":recheck")]
        self.assertEqual(check["do"], "record")
        self.assertIn("the job's log agrees", check["text"])
        self.assertIn(["gh", "run", "view", "--job", "9001", "--log-failed"], self.gh.calls)

    def test_a_runner_step_red_names_runner_and_orders_nobody(self):
        self.set_jobs(api_job(red="[04] tools"))
        planned = self.tick()
        (rec,) = [a for a in planned if a["kind"] == "step-record"]
        self.assertIn("(runner): runner: nobody ordered", rec["text"])
        self.assertEqual(self.orders(planned), [])

    def test_smuggle_mode_plans_nothing(self):
        self.set_jobs(api_job())
        with mock.patch("modes.asleep", lambda *a, **kw: True):
            planned = self.tick()
        self.assertEqual([a["kind"] for a in planned], ["step-failed"], "the line only")


class Cost(Watch):
    def test_one_jobs_list_a_round_while_a_job_runs_none_else(self):
        self.set_jobs(api_job())
        with gh_runs.round(None):
            for _ in range(2):
                step_red.events(str(self.main), RID, URL, self.gh.jobs[RID])
        self.assertEqual(sum(1 for c in self.gh.calls if "/actions/runs/777/jobs" in " ".join(c)), 1)
        self.gh.calls.clear()
        self.assertEqual(step_red.events(str(self.main), RID, URL, [view(api_job(status="completed"))]), [])
        self.assertEqual(self.gh.calls, [], "no job runs: no gh call")


EV = {"run": RID, "url": URL, "job": STACK, "step": RED, "runner": "hz01-host-a", "secs": 400, "at": "t"}
CTX = {"cars": FILES, "live": {"02", "09"}, "previous": [], "gate_jobs": set()}


class Verdict(unittest.TestCase):
    def test_the_car_whose_files_the_unit_names(self):
        v = step.verdict(EV, CTX)
        self.assertEqual((v["kind"], v["owner"], v["key"], v["recheck"]),
                         ("car", "02", f"triage:{RID}:stack-test/hub-e2e", "agrees"))

    def test_a_pipeline_car_owns_it(self):
        cars = FILES + [{"field": "11", "files": [".github/workflows/merge-to-main-cloud.yml"]}]
        v = step.verdict(EV, {**CTX, "cars": cars, "live": {"11"}})
        self.assertEqual((v["kind"], v["owner"], v["live"]), ("pipeline", "11", True))

    def test_a_repeat_or_a_red_within_seconds_orders_nobody(self):
        v = step.verdict(EV, {**CTX, "previous": [{"id": "700", "units": {"stack-test/hub-e2e": {}}}]})
        self.assertEqual((v["kind"], v["owner"], v["evidence"]["repeat_of"]), ("unsure", None, "700"))
        self.assertEqual(step.verdict({**EV, "secs": 2}, CTX)["kind"], "unsure")

    def test_no_runner_or_a_setup_step_is_runner(self):
        self.assertEqual(step.verdict({**EV, "runner": ""}, CTX)["kind"], "runner")
        self.assertEqual(step.verdict({**EV, "step": "Set up job"}, CTX)["kind"], "runner")

    def test_two_cars_named_or_a_step_without_a_unit_is_not_placed(self):
        two = [{"field": f, "files": ["code/typescript/apps/hub-e2e/a.ts"]} for f in ("02", "09")]
        self.assertEqual(step.verdict(EV, {**CTX, "cars": two})["placed"], "unplaced")
        self.assertEqual(step.verdict({**EV, "step": "[02] green before"}, CTX)["placed"], "unplaced")

    def test_the_target_train(self):
        landing = {"train": NAME, "state": "landing"}
        self.assertEqual(step.target(EV, landing, landing), "current")
        self.assertEqual(step.target({**EV, "merged_at": "t0"}, landing, landing), "next")
        self.assertEqual(step.target(EV, landing, {"train": "next", "state": "formed"}), "next")


if __name__ == "__main__":
    unittest.main()
