"""Hal2 plan 0695 step 27 (D33 F5): a land run whose runners are all busy and whose jobs keep finishing is a slow lane,
never STALLED-GATE (train 56-5, run 42106776290: 3/18 green after 49 min, every lane busy); the alarm only when no job
moved for MOVE_MIN or a job waits beside an idle runner with its labels. Fake `gh` answers, never GitHub."""

import datetime as dt
import unittest

import queue_gate as qg
import queue_watch as qw
import test_queue_watch as t

NOW = t.NOW


def jobs(started=(), completed=(), queued=()):
    """A jobs answer: running jobs started `started` min ago, finished ones completed `completed` min ago, queued ones
    waiting `queued` min (with labels)."""
    rows = [{"status": "in_progress", "started_at": t.ago(m), "labels": ["self-hosted"]} for m in started]
    rows += [{"status": "completed", "started_at": t.ago(m + 3), "completed_at": t.ago(m), "labels": ["self-hosted"]}
             for m in completed]
    rows += [{"status": "queued", "created_at": t.ago(m), "labels": ["self-hosted", "linux"]} for m in queued]
    return {"jobs": rows}


def runners(*states):
    """Runners as (status, busy) pairs, all labelled self-hosted + linux."""
    return {"runners": [{"name": f"r{i}", "status": s, "busy": b, "labels": [{"name": "self-hosted"}, {"name": "linux"}]}
                        for i, (s, b) in enumerate(states)]}


def fake_gh(job_doc, runner_doc):
    def run_json(argv, cwd=None):
        return runner_doc if argv[-1].startswith("repos/{owner}/{repo}/actions/runners") else job_doc
    return run_json


def stalled(job_doc, runner_doc, minutes=49):
    gate = lambda url: qg.gate_state(url, NOW, fake_gh(job_doc, runner_doc))  # noqa: E731
    head = t.ticket("56", pid=7, harvest=t.harvest(60, minutes))
    return [f["kind"] for f in qw.findings([head], NOW, t.LIVE, gate)]


BUSY = runners(("online", True), ("online", True))


class SlowLane(unittest.TestCase):
    def test_busy_lanes_with_jobs_finishing_is_no_stall(self):
        self.assertEqual(stalled(jobs(started=[30], completed=[4], queued=[20]), BUSY), [])

    def test_a_running_job_that_started_lately_counts_as_moving(self):
        self.assertEqual(stalled(jobs(started=[2], queued=[20]), BUSY), [])

    def test_no_job_moved_for_the_limit_is_stalled(self):
        found = stalled(jobs(started=[40], completed=[qg.MOVE_MIN + 5], queued=[20]), BUSY)
        self.assertEqual(found, ["STALLED-GATE"])

    def test_a_job_waiting_beside_an_idle_runner_is_stalled_though_jobs_finish(self):
        idle = runners(("online", True), ("online", False))
        self.assertEqual(stalled(jobs(completed=[1], queued=[qg.WAIT_MIN + 3]), idle), ["STALLED-GATE"])

    def test_a_fresh_queued_job_or_an_offline_or_unfit_runner_is_no_wait(self):
        idle = runners(("online", False))
        self.assertEqual(stalled(jobs(completed=[1], queued=[1]), idle), [], "queued for a minute")
        self.assertEqual(stalled(jobs(completed=[1], queued=[20]), runners(("offline", False))), [])
        mac = {"runners": [{"status": "online", "busy": False, "labels": [{"name": "macos"}]}]}
        self.assertEqual(stalled(jobs(completed=[1], queued=[20]), mac), [], "no runner has its labels")

    def test_under_45_min_in_the_step_never_alarms(self):
        self.assertEqual(stalled(jobs(completed=[60]), BUSY, minutes=30), [])

    def test_an_unreadable_gate_is_judged_by_time_alone(self):
        self.assertEqual(stalled(None, None), ["STALLED-GATE"])
        self.assertIsNone(qg.gate_state("https://ci/run/1", NOW, lambda a, c=None: None))
        self.assertIsNone(qg.gate_state("", NOW, fake_gh(jobs(), BUSY)), "no run id")

    def test_the_state_reports_idle_minutes_and_busy(self):
        s = qg.gate_state("https://github.com/o/r/actions/runs/42106776290", NOW, fake_gh(jobs(completed=[4]), BUSY))
        self.assertEqual((round(s["idle_min"]), s["busy"], s["waits_beside_idle"]), (4, True, False))


if __name__ == "__main__":
    unittest.main()
