import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tick  # noqa: E402

NOW = 100 * tick.DAY
PROJECT = "/r/hal2"


def state(**servant):
    return {"servant": {"unit": "code/rust/libs/a", "slot": "01", "plan": None, "spawned_ms": NOW - 60 * tick.MINUTE, **servant}}


def agent(agent_state, minutes_ago=1, slot="01"):
    return {"project": PROJECT, "slot": slot, "state": agent_state, "since": NOW - minutes_ago * tick.MINUTE}


def decide(st, agents=(), queue=(), landed=False, current_plan=None):
    return tick.decide(st, NOW, project=PROJECT, agents=list(agents), queue=list(queue), landed=landed, current_plan=current_plan)


class Decide(unittest.TestCase):
    def test_a_working_servant_is_waited_for(self):
        self.assertEqual(decide(state(), [agent("working")])["action"], "wait")

    def test_the_plan_comes_from_current_plan_once_it_is_a_plan_slug(self):
        self.assertEqual(decide(state(), [agent("working")], current_plan="0090-fix-loc-a")["plan"], "0090-fix-loc-a")
        self.assertIsNone(decide(state(), [agent("working")], current_plan="fix-login")["plan"])

    def test_landed_wins(self):
        self.assertEqual(decide(state(plan="0090-x"), [], landed=True)["action"], "landed")

    def test_a_held_queue_pauses(self):
        queue = [{"slot": "01", "state": "held", "hold": {"reason": "failed"}}]
        result = decide(state(), [agent("working")], queue)
        self.assertEqual(result["action"], "paused")
        self.assertIn("failed", result["reason"])

    def test_a_waiting_ticket_does_not_pause(self):
        self.assertEqual(decide(state(), [agent("working")], [{"slot": "01", "state": "waiting"}])["action"], "wait")

    def test_a_gone_servant_is_blocked_unless_it_is_starting(self):
        self.assertEqual(decide(state())["action"], "blocked")
        self.assertEqual(decide(state(spawned_ms=NOW - tick.MINUTE))["action"], "wait")
        self.assertEqual(decide(state(), [agent("working", slot="02")])["action"], "blocked")

    def test_a_long_dialog_blocks(self):
        self.assertEqual(decide(state(), [agent("blocked", 10)])["action"], "wait")
        self.assertEqual(decide(state(), [agent("blocked", 31)])["action"], "blocked")

    def test_a_long_idle_blocks(self):
        self.assertEqual(decide(state(), [agent("idle", 59)])["action"], "wait")
        for agent_state in ("idle", "done", "sleeping", "ended", "failed"):
            self.assertEqual(decide(state(), [agent(agent_state, 61)])["action"], "blocked", agent_state)


class Units(unittest.TestCase):
    def test_next_unit_skips_busy_and_blocked(self):
        units = [{"unit": "a", "busy": True}, {"unit": "b", "busy": False}, {"unit": "c", "busy": False}]
        self.assertEqual(tick.next_unit(units, {"blocked": {"b": NOW + 1}}, NOW)["unit"], "c")
        self.assertEqual(tick.next_unit(units, {"blocked": {"b": NOW - 1}}, NOW)["unit"], "b")
        self.assertIsNone(tick.next_unit(units[:1], {}, NOW))

    def test_a_unit_still_over_twice_is_skipped_30_days(self):
        st = {}
        self.assertIsNone(tick.after_landing(st, "a", True, NOW))
        self.assertIn("30 days", tick.after_landing(st, "a", True, NOW))
        self.assertEqual(st["blocked"]["a"], NOW + tick.GIVE_UP_FOR)

    def test_a_clean_landing_resets_the_attempts(self):
        st = {"attempts": {"a": 1}}
        tick.after_landing(st, "a", False, NOW)
        self.assertNotIn("a", st["attempts"])

    def test_rearm_after_six_days(self):
        self.assertFalse(tick.needs_rearm({"started_ms": NOW - 5 * tick.DAY}, NOW))
        self.assertTrue(tick.needs_rearm({"started_ms": NOW - 7 * tick.DAY}, NOW))


if __name__ == "__main__":
    unittest.main()
