"""Hal2 plan 0695 step 20 (D25, tollman L259): a landing or train stuck in its local phase (own-cli build, push; no land
run yet) past 20 min is the finding STALLED-PUSH, alarmed once as the push-only case `queue-stalled-push`; one that got
its land run is not (only STALLED-GATE can then fire). Reuses test_queue_watch's fixtures; never a real queue or alarm."""

import datetime as dt
import unittest

import queue_watch as qw
import test_queue_watch as t


def local(started: float, step: str = "own-cli") -> dict:
    """A running harvest still in its local phase: no land run (run_url empty)."""
    return {**t.harvest(started, started), "step": step, "run_url": None, "jobs": 0, "jobs_green": 0}


class StalledPush(unittest.TestCase):
    def kinds(self, head):
        return [f["kind"] for f in qw.findings([head], t.NOW, t.LIVE)]

    def test_a_local_phase_past_the_limit_is_stalled(self):
        found = qw.findings([t.ticket("28", pid=7, harvest=local(25))], t.NOW, t.LIVE)
        self.assertEqual([f["kind"] for f in found], ["STALLED-PUSH"])
        self.assertIn("local phase (own-cli) for 25 min, no land run yet", found[0]["line"])

    def test_under_the_limit_or_with_its_land_run_is_not(self):
        self.assertEqual(self.kinds(t.ticket("28", pid=7, harvest=local(qw.LOCAL_MIN - 1))), [])
        self.assertEqual(self.kinds(t.ticket("28", pid=7, harvest=t.harvest(25, 5))), [], "got its land run")
        self.assertEqual(self.kinds(t.ticket("28", pid=7, harvest=t.harvest(25, 25))), [], "gate under 45")

    def test_a_long_local_step_is_not_also_a_stalled_gate(self):
        self.assertEqual(self.kinds(t.ticket("28", pid=7, harvest=local(60, "push"))), ["STALLED-PUSH"])


class StalledPushAlarm(t.Duty):
    def stalled(self):
        return [t.ticket("28", pid=7, harvest=local(25))]

    def test_alarmed_exactly_once_on_the_next_sighting(self):
        first = self.tick(self.stalled())
        self.assertEqual([a["do"] for a in first], ["wake"], "first sight: a wake, no alarm")
        later = t.NOW + dt.timedelta(minutes=5)
        acts = self.tick(self.stalled(), later)
        self.assertEqual([(a["kind"], a["do"]) for a in acts], [("alarm", "run")])
        self.assertEqual(acts[0]["argv"][2], "queue-stalled-push", "push only: not a stuck (ringing) case")
        self.assertEqual(self.tick(self.stalled(), later + dt.timedelta(minutes=5)), [], "once")

    def test_a_phase_that_got_its_land_run_never_alarms(self):
        for minutes in (0, 5, 40):
            queue = [t.ticket("28", pid=7, harvest=t.harvest(25, 5))]
            self.assertEqual(self.tick(queue, t.NOW + dt.timedelta(minutes=minutes)), [])

    test_a_new_finding_wakes_once_and_is_kept_with_its_schema = None
    test_first_seen_carries_and_past_30_min_alarms_once = None


if __name__ == "__main__":
    unittest.main()
