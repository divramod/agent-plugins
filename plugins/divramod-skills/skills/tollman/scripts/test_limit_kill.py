"""Hal2 plan 0719 step 1: a red job the time limit killed, with no finding line left, is the runner's load (learning
L267), in both triages (triage.py for a train's landing, run_triage.py for a finished land run), and red_orders.py
finds a reason for it. The replay is train 56-7's run 42133755939, job c6-01-lint (fixtures/limit_kill: the job's
steps and its log, trimmed): records-check ended at the gate's own 20 minutes (`⏳ 00:20:00`) on a loaded hz01 with
nothing but `##[error]gate: lint: records-check failed` in its log, and the triage named a car's order for it.
A limit kill with a finding of its own (a failing test, an error line that is no frame) stays the car's."""

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import fix_wait
import red_orders
import run_triage
import run_triage_limit as limit
import run_triage_read as read
import triage

FIX = Path(__file__).with_name("fixtures") / "limit_kill"
RID = "42133755939"
URL = f"https://github.com/divramod/hal2/actions/runs/{RID}"
JOB = json.loads((FIX / f"run-{RID}.c6-01-lint.job.json").read_text())
LOG = (FIX / f"run-{RID}.c6-01-lint.log").read_text()
RUN = {"id": RID, "url": URL, "sha": "1" * 40}
CAR = {"field": "20", "files": ["code/rust/apps/hal2-cli-state/src/scratch.rs"]}
CTX = {"cars": [CAR], "paths": [], "live": {"20"}, "plans": {}, "previous": [], "others": [], "gate_jobs": set(),
       "dedup": {"orders": [], "wagons": []}}


def with_line(text: str, line: str, before: str = "[12] 💥") -> str:
    """The log with one more line of step 12 just before the gate's end marker."""
    out = []
    for raw in text.splitlines():
        if before in raw:
            out.append(f"c6-01-lint\t[12] records-check\t2026-11-06T00:54:51.0000000Z {line}")
        out.append(raw)
    return "\n".join(out)


def verdicts(log: str = LOG, job: dict = JOB) -> dict:
    return {v["evidence"]["unit"]: v for v in run_triage.triage(RUN, [job], log, copy.deepcopy(CTX))["verdicts"]}


class Parser(unittest.TestCase):
    def test_the_replay_is_a_gate_kill_at_its_declared_20_minutes(self):
        unit = read.units([JOB], LOG)[0]
        found = read.facts(unit["lines"], unit["data"])["limit"]
        self.assertEqual({k: found[k] for k in ("by", "step", "secs", "limit")},
                         {"by": "gate", "step": "records-check", "secs": 1200, "limit": 1200})
        self.assertEqual(found["match"], "job limit: records-check after 00:20:00, the gate's 20 min")

    def test_a_step_that_ended_before_its_limit_is_no_kill(self):
        early = LOG.replace("⏳ 00:20:00", "⏳ 00:19:12")
        unit = read.units([JOB], early)[0]
        self.assertIsNone(read.facts(unit["lines"], unit["data"])["limit"])

    def test_a_log_that_declares_no_limit_is_never_taken_for_a_kill(self):
        bare = "\n".join(t for t in LOG.splitlines() if '"timeout"' not in t)
        unit = read.units([JOB], bare)[0]
        self.assertIsNone(read.facts(unit["lines"], unit["data"])["limit"])

    def test_githubs_own_data_is_a_kill_too(self):
        timed = dict(JOB, conclusion="timed_out")
        self.assertEqual(limit.kill(timed, ["x"])["by"], "github")
        self.assertEqual(limit.kill(None, ["##[error]The job running on runner hz01 has exceeded the maximum "
                                           "execution time of 45 minutes."])["by"], "github")
        self.assertIsNone(limit.kill(dict(JOB, conclusion="cancelled"), ["##[error]The operation was canceled."]))

    def test_a_unit_without_lines_has_no_evidence(self):
        self.assertIsNone(read.limit_kill(dict(JOB, conclusion="timed_out"), []))

    def test_holds_recomputes_from_the_numbers(self):
        found = limit.gate(read.units([JOB], LOG)[0]["lines"])
        self.assertTrue(limit.holds(found))
        self.assertFalse(limit.holds({**found, "secs": found["limit"] - 1}))
        self.assertFalse(limit.holds({**found, "secs": found["limit"] + limit.SLACK + 1}))
        self.assertFalse(limit.holds(None))


class RunTriage(unittest.TestCase):
    def test_the_replay_is_a_runner_red_never_a_car_s(self):
        v = verdicts()["lint"]
        self.assertEqual((v["kind"], v["owner"], v["recheck"]), ("runner", None, "agrees"))
        e = v["evidence"]
        self.assertTrue(e["limit"])
        self.assertEqual(e["match"], "job limit: records-check after 00:20:00, the gate's 20 min")
        self.assertEqual(e["kill"]["limit"], 1200)

    def test_a_limit_kill_with_a_failing_test_stays_the_car_s(self):
        for line in ("not ok 7 records: a scratch store is declared", "FAIL [  3.2s] hal2-state scratch::leaves_nothing",
                     "error[E0599]: no method named `scratch` found for struct `Store`",
                     "a suite failed: hal2-cli-state"):
            with self.subTest(line=line):
                v = verdicts(with_line(LOG, line))["lint"]
                self.assertNotEqual(v["kind"], "runner")
                self.assertNotIn("limit", v["evidence"])

    def test_a_build_phase_timeout_stays_the_pipeline_s(self):
        v = verdicts(with_line(LOG, "phase build: failed after 600s (exit 124)"))["lint"]
        self.assertNotEqual(v["kind"], "runner")

    def test_a_normal_red_without_a_limit_is_judged_as_before(self):
        quick = LOG.replace("⏳ 00:20:00", "⏳ 00:03:10")
        v = verdicts(quick)["lint"]
        self.assertIn(v["kind"], ("unplaced", "car", "unsure"))
        self.assertNotIn("limit", v["evidence"])

    def test_the_recheck_turns_a_limit_verdict_whose_numbers_do_not_hold_into_unsure(self):
        v = verdicts()["lint"]
        bad = copy.deepcopy(v)
        bad["evidence"]["kill"]["secs"] = 300
        self.assertNotEqual(run_triage.check.recheck(bad["evidence"])[0], "runner")

    def test_red_orders_finds_a_reason_for_the_job(self):
        red = [v for v in run_triage.triage(RUN, [JOB], LOG, copy.deepcopy(CTX))["verdicts"]]
        entry = {"run": RID, "reds": fix_wait.compact(red, "2026-11-06T01:02:00Z")}
        rows = [{"kind": "formed", "train": "56-7", "cars": []}, {"kind": "run", "train": "56-7", "run": URL}]
        with mock.patch.object(red_orders.train_state, "lines", lambda main: list(rows)):
            result = red_orders.check("/m", [RID], read=lambda rid: [JOB, dict(JOB, name="gate")],
                                      entries=lambda rid: entry)
        self.assertEqual(result["missing"], 0, red_orders.lines(result))
        self.assertEqual(result["runs"][0]["reds"], [{"job": "c6-01-lint", "verdict": "reason",
                                                      "why": "run triage: runner"}])
        self.assertEqual(red_orders.exit_code(result), 0)


class TrainTriage(unittest.TestCase):
    def classify(self, log: str = LOG, red=(JOB,), history=None):
        return triage.classify({"id": RID, "url": URL}, list(red), log, {"cars": [CAR], **(history or {})})

    def test_the_replay_is_a_runner_red(self):
        v = self.classify()
        self.assertEqual(v["kind"], "runner")
        self.assertTrue(v["evidence"]["limit"])
        self.assertEqual(v["evidence"]["match"], "job limit: records-check after 00:20:00, the gate's 20 min")

    def test_the_log_may_name_no_job_it_has_no_lines_for(self):
        self.assertEqual(self.classify(red=[{"name": "c6-01-lint"}])["kind"], "runner", "a job read without steps")
        self.assertEqual(self.classify(log="")["kind"], "car", "no lines, no evidence")

    def test_a_limit_kill_with_a_finding_stays_the_car_s(self):
        v = self.classify(with_line(LOG, "not ok 7 records: a scratch store is declared"))
        self.assertEqual(v["kind"], "car")
        self.assertNotIn("limit", v["evidence"])

    def test_another_red_job_keeps_the_run_the_car_s(self):
        other = {"name": "c2-06-ts-build-test-linux", "conclusion": "failure", "steps": []}
        log = LOG + "\nc2-06-ts-build-test-linux\t[05] gate ts-build-test-linux\tFAIL src/a.test.ts > a > b\n"
        self.assertEqual(self.classify(log, red=[JOB, other])["kind"], "car")


if __name__ == "__main__":
    unittest.main()
