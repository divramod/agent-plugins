"""Hal2 plan 0522 step 6 (D16, D17): every red job of a train's live land run is ordered to its car as soon as it is
red, one order per red job, and a job ordered or handed to the session once is never ordered again. The regression replays
train 32's run 41167356202 of 2026-10-31 (fixtures/run-41167356202.json: its three red jobs in the order the watch
recorded them, an excerpt of each one's GitHub job log, the four cars' files): gh gave no failed log while the run
ran, so the triage named no car, nothing was ordered, the second red did not refresh the wake, and at the run's end
car 27 was ordered for bash-test (05:01Z), which the session had fixed on the carrier itself (04:38Z)."""
# enforces .adr/deterministic-first.md and .adr/tollman.md

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import early_order
import job_error
import train_state
import triage
from gh_fake import FakeGh, job, run

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "run-41167356202.json").read_text())
RID, URL, NAME = FIXTURE["run"], FIXTURE["url"], FIXTURE["train"]
PLANS = {"27": "0467-train-build-warm", "15": "0482-pre-push-green-keys", "20": "0493-table-polish",
         "30": "0470-project-lifecycle-view"}
TRAIN = {"train": NAME, "state": "landing", "orders": [],
         "cars": [{"field": c["field"], "plan": PLANS[c["field"]]} for c in FIXTURE["cars"]]}
BASH, TS, LINUX = (j["name"] for j in FIXTURE["jobs"])


class Run41167356202(unittest.TestCase):
    """The tollman's ticks at the three `job-failed` records and at the run's end, each action carried out as tick
    does: its key into the log, an early order's line into the train state."""

    def setUp(self):
        self.main = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.main, ignore_errors=True))
        self.log, self.rows, self.done = [], [], []
        logs = {str(j["databaseId"]): j["log"] for j in FIXTURE["jobs"]}
        self.gh = FakeGh([run(RID, "land/train-32-9", "2026-10-31T04:09:07Z", status="in_progress")],
                         job_logs=logs).start(self)
        history = {"main": "", "other": None, "cars": FIXTURE["cars"], "pauses": [], "smuggles": []}
        for target, value in ((early_order, "read_log"), (train_state, "lines"), (triage, "gather")):
            fake = {"read_log": lambda main, role: self.log, "lines": lambda main: self.rows,
                    "gather": lambda main, train, url, names, jobs, tickets: (
                        {"id": RID, "url": url, "cancelled": False}, [], self.run_log, history)}[value]
            p = mock.patch.object(target, value, fake)
            p.start()
            self.addCleanup(p.stop)
        self.run_log = ""  # gh's `run view --log-failed`: nothing while the run runs

    def jobs(self, n: int) -> list[dict]:
        """The run's jobs when the watch had recorded the first `n` reds: those red, one still running."""
        red = [{**job(j["name"]), "databaseId": j["databaseId"]} for j in FIXTURE["jobs"][:n]]
        return red + [job("d1-01-stack-test", None)]

    def tick(self, n: int, at: str) -> list[dict]:
        out = early_order.actions(self.main, self.main, TRAIN, URL, RID, self.jobs(n))
        for a in out:
            self.log.append({"at": at, "key": a["key"], "kind": a["kind"]})
            if a["kind"] == "early-order":
                field = a["argv"][3]
                self.rows.append({"kind": "order", "train": NAME, "run": URL, "field": field, "jobs": []})
        self.done.append(out)
        return out

    def test_each_red_is_ordered_to_its_car_at_once_and_none_twice(self):
        first = self.tick(1, "2026-10-31T04:23:43Z")  # bash-test: its red names no car's file (the session's fix)
        self.assertEqual([(a["kind"], a["key"]) for a in first], [
            ("early-red", f"early-red:{RID}:{BASH}"), ("train-red", f"train-red:{RID}")])
        self.assertIn(f"{BASH}: yours", first[-1]["text"])
        self.assertNotIn("gate/test.bats", first[-1]["text"], "a passing test's path names no culprit")

        second = self.tick(2, "2026-10-31T04:45:30Z")  # ts-test: app-keys.json is car 30's
        orders = [a for a in second if a["kind"] == "early-order"]
        self.assertEqual([(a["slot"], a["key"]) for a in orders], [("30", f"early-order:{RID}:{TS}:30")])
        why = orders[0]["argv"][orders[0]["argv"].index("--why") + 1]
        self.assertEqual(why, f"{TS}: × are in src/commands/app-keys.json 14ms", "the runner's red line")
        wake = second[-1]
        self.assertEqual((wake["kind"], wake["key"]), ("train-red", f"train-red:{RID}:{TS}"), "the red refreshes it")
        for part in (BASH, TS, f"{TS}: ordered to 30", f"{BASH}: told before"):
            self.assertIn(part, wake["text"])

        third = self.tick(3, "2026-10-31T04:50:36Z")  # bash-test-linux: gate/test-abort.bats is car 27's
        self.assertEqual([a["slot"] for a in third if a["kind"] == "early-order"], ["27"])
        self.assertTrue(all(n in third[-1]["text"] for n in (BASH, TS, LINUX)), "train-red names every red")
        argv = next(a for a in third if a["kind"] == "early-order")["argv"]
        why = argv[argv.index("--why") + 1]
        self.assertTrue(why.startswith(f"{LINUX}: not ok 6 only column 02's lanes ask"), why)

        self.gh.runs[0] = run(RID, "land/train-32-9", "2026-10-31T04:09:07Z")  # 05:00:27Z: the run has finished
        self.run_log = "\n".join(j["log"] for j in FIXTURE["jobs"])
        self.assertEqual(self.tick(3, "2026-10-31T05:01:13Z"), [], "no second order: never 27 for bash-test (D17)")
        self.assertEqual([r["field"] for r in self.rows], ["30", "27"])

    def test_a_job_the_session_ordered_by_hand_is_not_ordered_again(self):
        self.rows.append({"kind": "order", "train": NAME, "run": URL, "field": "30", "jobs": ["ts-test"]})
        out = self.tick(2, "2026-10-31T04:45:30Z")
        self.assertEqual([a["key"] for a in out if a["kind"] == "early-red"], [f"early-red:{RID}:{BASH}"])
        self.assertNotIn("early-order", [a["kind"] for a in out])

    def test_the_job_log_is_read_while_the_run_runs_and_kept_once(self):
        state = Path(self.main) / "state"
        state.mkdir()
        j = {**job(TS), "databaseId": FIXTURE["jobs"][1]["databaseId"]}
        with mock.patch.object(job_error.mtm_scan, "state_dir", return_value=state):
            text = job_error.job_log(self.main, j)
            self.assertNotIn("##[group]", text, "the failed step's own lines only")
            self.assertIn("are in src/commands/app-keys.json", text)
            asked = len(self.gh.calls)
            self.assertEqual(job_error.job_log(self.main, j), text)
            self.assertEqual(len(self.gh.calls), asked, "a completed job's log is kept (cache/job-logs)")
        self.assertEqual(job_error.job_log(self.main, {**j, "status": "in_progress"}), "", "not while it runs")


class Also(unittest.TestCase):
    def test_a_second_red_job_of_a_car_grows_its_open_early_order(self):
        rows = [{"kind": "formed", "train": "t", "slot": "c", "cars": [{"field": "27"}]},
                {"kind": "started", "train": "t", "at": "x"},
                {"kind": "order", "train": "t", "field": "27", "id": "27-fix-4", "jobs": ["bash-test"], "why": "a"},
                {"kind": "order", "train": "t", "field": "27", "id": "27-fix-4", "also": "27-fix-4",
                 "jobs": ["bash-test-linux"], "why": "b"}]
        train = train_state.standing(rows)
        self.assertEqual(train["state"], "landing")
        self.assertEqual([(o["id"], o["jobs"], o["why"]) for o in train["orders"]],
                         [("27-fix-4", ["bash-test", "bash-test-linux"], "a; b")])
        import orders
        self.assertEqual(orders.next_id(rows, "27"), "27-fix-2", "an `also` line opens no order")


if __name__ == "__main__":
    unittest.main()
