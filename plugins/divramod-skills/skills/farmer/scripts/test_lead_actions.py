"""The lead duty's actions per field class (hal2 plan 0514 step 5, D8, D11): code, no model, no real session."""

import datetime as dt
import unittest

import duties
import lead_actions
import tick


def need(kind, slot="12", plan="0600-x", at="2026-11-03T10:00:00Z", session="s12", since=1, **kw):
    return {"kind": kind, "why": f"why {kind}", "slot": slot, "pane": f"%{slot}", "session": session, "since": since,
            "plan": plan, "field": {"run_state": {"at": at}}, "said": "", **kw}


def ctx(log=()):
    return {"top": "/x/farmer", "main": "/x/hal2", "now": dt.datetime.now(dt.timezone.utc), "log": list(log),
            "duties": {"lead"}, "panes": {}, "agents_by_pane": {}, "landing": set()}


def plan(needs, log=(), lessons="none"):
    c = ctx(log)
    old = lead_actions.lessons_file
    lead_actions.lessons_file = lambda: None  # no lessons file: `lessons` is read from the text below
    try:
        acts = lead_actions.acts(needs, set(), lessons)
    finally:
        lead_actions.lessons_file = old
    return tick.fresh(acts, log, c["now"])


class Actions(unittest.TestCase):
    def test_done_not_hitched_told_once_per_plan(self):
        first = plan([need("done-not-hitched")], lessons="## done-not-hitched\n")
        self.assertEqual([(a["do"], a["slot"]) for a in first], [("send", "12")])
        self.assertIn("plan.py", first[0]["text"])
        self.assertEqual(first[0]["pane"], "%12")
        log = [{"at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "key": first[0]["key"]}]
        self.assertEqual(plan([need("done-not-hitched")], log, lessons="## done-not-hitched\n"), [])
        again = plan([need("done-not-hitched", plan="0601-y")], log, lessons="## done-not-hitched\n")
        self.assertEqual(len(again), 1)  # another plan of the field is told again

    def test_text_names_mtm_without_plan_end(self):
        old = lead_actions.has_end
        lead_actions.has_end = lambda: False
        try:
            a = plan([need("done-not-hitched")], lessons="## done-not-hitched\n")
        finally:
            lead_actions.has_end = old
        self.assertIn("/mtm", a[0]["text"])

    def test_pushing_is_never_told(self):
        a = plan([need("pushing")], lessons="")
        self.assertEqual([x["do"] for x in a], ["record"])

    def test_landed_is_recorded_for_the_prune(self):
        a = plan([need("landed")])
        self.assertEqual([x["do"] for x in a], ["record"])
        self.assertIn("prune", a[0]["text"])

    def test_waiting_fields_batched_into_one_wake(self):
        a = plan([need("waiting", "04", session="a"), need("waiting", "07", session="b"), need("hitched", "09")])
        wakes = [x for x in a if x["do"] == "wake"]
        self.assertEqual(len(wakes), 1)
        self.assertIn("field 04", wakes[0]["text"])
        self.assertIn("field 07", wakes[0]["text"])

    def test_unknown_stall_class_wakes_once_known_never(self):
        a = plan([need("blocked-plan")], lessons="# Lessons\n")
        wake = [x for x in a if x["do"] == "wake"]
        self.assertEqual(len(wake), 1)
        log = [{"at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "key": wake[0]["key"]}]
        self.assertEqual([x for x in plan([need("blocked-plan")], log, lessons="# Lessons\n") if x["do"] == "wake"], [])
        self.assertEqual([x for x in plan([need("blocked-plan")], lessons="## blocked-plan\ntext") if x["do"] == "wake"], [])
        self.assertEqual([x for x in plan([need("blocked-plan")], lessons="class: blocked-plan") if x["do"] == "wake"], [])

    def test_quiet_round_plans_nothing(self):
        self.assertEqual(plan([]), [])

    def test_duty_planner_uses_it(self):
        out = duties.plan_lead({}, ctx(), {"needs_help": [need("landed")]})
        self.assertEqual([a["do"] for a in out], ["record"])


if __name__ == "__main__":
    unittest.main()
