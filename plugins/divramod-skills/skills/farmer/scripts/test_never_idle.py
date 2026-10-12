"""Hal2 plan 0137: slot 12 sat idle 21:24-06:45 in plan 0131, "waiting for your go", and the farmer never woke.

The replay: the session's overnight state through lead_scan.classify, duties.plan_lead and tick.fresh, with the
farmer's log as it was (two `ask` entries for 12, the user's answer logged as a `decision`, never `answered`).
"""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import duties
import lead_scan
import tick

IDLE_SINCE = dt.datetime(2026, 10, 4, 21, 24)
NOW = dt.datetime(2026, 10, 5, 6, 45)
SESSION = "2f91aa8a-412f-4ea2-95e0-fbe1bc07510b"
SAID = ("Step 7's offline part is committed (4dd54818). The production steps are decided in the plan, but they "
        "touch hal9k and a paid server.\n\nI'm waiting for your go to read the hal2-ci-wake log on hal9k")
LOG = [
    {"at": "2026-10-04T18:03:10", "kind": "ask", "slot": "12", "what": "user decides the Linux runner type"},
    {"at": "2026-10-04T18:14:18", "kind": "ask", "slot": "12", "what": "user: go for production deploy"},
    {"at": "2026-10-04T18:23:29", "kind": "decision", "slot": "12", "what": "user: go (1a), CCX33 (2a)"},
]
AGENT = {"state": "idle", "since": int(IDLE_SINCE.timestamp() * 1000), "slot": "12", "pane_id": "t:12",
         "session_id": SESSION, "plan": "0131 · landings through GitHub Actions, hooks removed",
         "current_plan": "0131-landings-through-github-actions-hooks-removed", "context_percent": 31}


def need(kind, why):
    return {"kind": kind, "why": why, "slot": "12", "pane": "t:12", "session": SESSION, "since": AGENT["since"],
            "said": SAID, "plan": AGENT["plan"]}


def ctx(log):
    return {"top": "/x/farmer", "main": "/x/hal2", "now": NOW, "log": log, "duties": {"mtm", "lead", "watch"},
            "panes": {"12": "t:12"}, "agents_by_pane": {}, "landing": set()}


def wakes(log, now=NOW):
    hit = lead_scan.classify(AGENT, SAID, now.timestamp())
    planned = duties.plan_lead({}, ctx(log), {"needs_help": [need(*hit)]})
    return [(a["do"], a["kind"], a["slot"]) for a in tick.fresh(planned, list(log), now)]


class SlotTwelveOvernight(unittest.TestCase):
    def test_waiting_for_your_go_is_a_question(self):
        for said in ("I'm waiting for your go to read the log", "I wait for your go.", "Waiting for your answer.",
                     "Say the word and I deploy: your go decides."):
            self.assertTrue(lead_scan.WAITS_FOR_USER.search(said), said)
        self.assertEqual(lead_scan.classify(AGENT, SAID, NOW.timestamp())[0], "asks")

    def test_the_replay_wakes_the_farmer(self):
        self.assertEqual(wakes(LOG), [("wake", "asks", "12")])

    def test_a_decision_closes_an_open_ask(self):
        self.assertEqual(tick.waiting_for_user(LOG), set())
        self.assertEqual(tick.waiting_for_user(LOG[:2]), {"12"})
        self.assertEqual(tick.waiting_for_user(LOG[:2] + [{"kind": "answer", "slot": "12"}]), set())

    def test_an_open_ask_never_holds_a_lead_wake_only_what_is_typed(self):
        self.assertEqual(wakes(LOG[:2]), [("wake", "asks", "12")])
        going = dict(need("idle-in-plan", "idle"), said="Done.\n\nNext I'll run step 8.")
        planned = duties.plan_lead({}, ctx(LOG[:2]), {"needs_help": [going]})
        self.assertEqual(tick.fresh(planned, LOG[:2], NOW), [])

    def test_a_stop_still_there_an_hour_later_wakes_again(self):
        key = f"lead:{SESSION}:{AGENT['since']}"
        woke = lambda minutes: LOG + [{"at": (NOW - dt.timedelta(minutes=minutes)).isoformat(), "key": key}]
        self.assertEqual(wakes(woke(30)), [])
        self.assertEqual(wakes(woke(61)), [("wake", "asks", "12")])

    def test_idle_in_a_plan_wakes_whatever_the_prompt_box_holds(self):
        quiet = dict(AGENT, draft="relay: 1a 2a")  # hal2's state comes from hooks; a draft changes nothing
        self.assertEqual(lead_scan.classify(quiet, "Step 6 done.", NOW.timestamp())[0], "idle-in-plan")


class RelayedGo(unittest.TestCase):
    def test_the_marker_is_documented_verbatim_where_it_is_accepted(self):
        skills = Path(__file__).resolve().parents[2]
        for doc in ("farmer/SKILL.md", "farmer/instructions/lead.md", "plan/SKILL.md", "mtm/SKILL.md"):
            self.assertIn(duties.USER_DECIDED, (skills / doc).read_text(), doc)

    def test_a_relayed_go_quotes_the_users_words(self):
        self.assertEqual(duties.user_decided("12-3", 'go "1a" 2a'), "farmer [12-3]: the user decided: \"go '1a' 2a\"")


class HandledExpires(unittest.TestCase):
    def test_a_handled_mark_counts_for_an_hour(self):
        with tempfile.TemporaryDirectory() as d:
            old, lead_scan.DATA = lead_scan.DATA, Path(d)
            try:
                f = Path(d) / "hal2" / "lead.jsonl"
                f.parent.mkdir()
                rows = [{"at": (NOW - dt.timedelta(minutes=m)).isoformat(), "session": s, "since": 1, "what": "x"}
                        for m, s in ((10, "fresh"), (90, "stale"))]
                f.write_text("\n".join(map(json.dumps, rows)) + "\nnot json\n")
                self.assertEqual(lead_scan.handled("/x/hal2", NOW.timestamp()), {("fresh", 1)})
            finally:
                lead_scan.DATA = old


if __name__ == "__main__":
    unittest.main()
