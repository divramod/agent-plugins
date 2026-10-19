"""Hal2 plan 0360 step 25 (D75 3, D76): in smuggle mode the farmer tells every finished, harvested field (a hitched
ticket) "smuggle mode: run /merge-to-main now", once per field and mode period, without asking the user; in production mode it
says nothing; nothing while the tollman's sleep flag stands (plan 0375 D4: the tollman tells them). The queue is data:
no real hal2-cli-git, no session."""

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer
import queue_mode
import tick

NOW = dt.datetime(2026, 10, 17, 12, 30)
SMUGGLE = {"mode": "smuggle", "by": "user", "at": "2026-10-17T12:00:00Z", "why": "the runners are down"}


def hitched(slot, **kw):
    return {"slot": slot, "state": "waiting", "ready": {"head": slot[0] * 40, "at": "2026-10-17T11:00:00Z"}, **kw}


def ctx(log=()):
    return {"top": "/x/farmer-hal2", "main": "/x/hal2", "now": NOW, "log": list(log), "panes": {"07": "%7"}}


def planned(doc, log=()):
    return tick.fresh(queue_mode.plan({}, ctx(log), doc), list(log), NOW)


class SmuggleMode(unittest.TestCase):
    QUEUE = [hitched("07"), hitched("09"), hitched("31"), hitched("tollman-hal2"), hitched("11", rides_with="x"),
             {"slot": "12", "state": "waiting", "ready": None}, hitched("13", state="active")]

    def setUp(self):  # the tollman's field (its sleep flag) in a scratch folder, never the host's
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.field = Path(d.name)
        patch = mock.patch.object(queue_mode.roles, "slot_dir", lambda main, role: self.field)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_mode_is_production_without_one(self):
        self.assertEqual(queue_mode.of({})["mode"], "production")
        self.assertEqual(queue_mode.of({"mode": None})["mode"], "production")
        self.assertEqual(queue_mode.of({"mode": SMUGGLE}), SMUGGLE)
        self.assertTrue(queue_mode.smuggle(SMUGGLE))
        self.assertFalse(queue_mode.smuggle(queue_mode.of({})))

    def test_each_hitched_field_is_told_once_per_mode_period(self):
        out = planned({"queue": self.QUEUE, "mode": SMUGGLE})
        self.assertEqual([(a["slot"], a["do"], a["key"]) for a in out],
                         [("07", "send", "smuggle-mode:07:2026-10-17T12:00:00Z"),
                          ("09", "send", "smuggle-mode:09:2026-10-17T12:00:00Z")])
        self.assertEqual(out[0]["pane"], "%7")
        self.assertTrue(out[0]["text"].startswith(queue_mode.LEAD + ": smuggle mode: run /merge-to-main now"), out[0]["text"])
        self.assertIn("since 2026-10-17T12:00:00Z (by user)", out[0]["text"])
        log = [{"at": NOW.isoformat(), "key": a["key"]} for a in out]
        self.assertEqual(planned({"queue": self.QUEUE, "mode": SMUGGLE}, log), [], "told once")
        again = dict(SMUGGLE, at="2026-10-18T08:00:00Z")
        self.assertEqual(len(planned({"queue": self.QUEUE, "mode": again}, log)), 2, "a new smuggle period")

    def test_production_mode_tells_nobody(self):
        self.assertEqual(planned({"queue": self.QUEUE}), [])
        self.assertEqual(planned({"queue": self.QUEUE, "mode": dict(SMUGGLE, mode="production")}), [])

    def test_the_effective_mode_of_an_entry(self):
        smuggle, production = {"mode": "smuggle"}, {"mode": "production"}
        self.assertEqual(queue_mode.effective({}, smuggle), "smuggle", "no field: the queue's")
        self.assertEqual(queue_mode.effective({}, {}), "production")
        self.assertEqual(queue_mode.effective({"mode": "smuggle"}, production), "smuggle", "an older CLI: its own mode")
        self.assertEqual(queue_mode.effective({"mode": None, "effective_mode": "production"}, smuggle), "production")
        self.assertEqual(queue_mode.effective({"mode": "smuggle", "effective_mode": "smuggle"}, production), "smuggle")

    def test_an_entry_set_to_smuggle_is_told_in_production_mode_once(self):
        doc = {"queue": [hitched("07", mode="smuggle", effective_mode="smuggle", seq=41),
                         hitched("09", mode=None, effective_mode="production", seq=42)]}
        out = planned(doc)
        self.assertEqual([(a["slot"], a["key"]) for a in out], [("07", "smuggle-mode:07:entry41")])
        self.assertIn("set to smuggle", out[0]["text"])
        self.assertTrue(out[0]["text"].startswith(queue_mode.LEAD + ": smuggle mode: run /merge-to-main now"))
        log = [{"at": NOW.isoformat(), "key": out[0]["key"]}]
        self.assertEqual(planned(doc, log), [], "told once")
        self.assertEqual(len(planned({"queue": [hitched("07", mode="smuggle", seq=43)]}, log)), 1, "a new entry")

    def test_an_entry_in_production_is_not_told_in_smuggle_mode(self):
        doc = {"mode": SMUGGLE, "queue": [hitched("07", mode="production", effective_mode="production", seq=1),
                                           hitched("09", mode=None, effective_mode="smuggle", seq=2),
                                           hitched("12")]}
        self.assertEqual([a["slot"] for a in planned(doc)], ["09", "12"], "12: no fields, the queue's mode")
        self.assertEqual(planned(doc)[0]["key"], "smuggle-mode:09:2026-10-17T12:00:00Z")

    def test_an_asleep_tollman_tells_every_hitched_field_itself(self):
        self.assertEqual(len(planned({"queue": self.QUEUE, "mode": SMUGGLE})), 2, "awake: the farmer's word")
        flag = self.field / "roles" / "tollman" / "sleep.json"
        flag.parent.mkdir(parents=True)
        flag.write_text('{"schema": 1, "by": "user", "at": "2026-10-17T12:10:00Z", "why": ""}\n')
        self.assertTrue(queue_mode.tollman_asleep("/x/hal2"))
        self.assertEqual(planned({"queue": self.QUEUE, "mode": SMUGGLE}), [], "asleep: the tollman's word")

    def test_the_lead_round_carries_it(self):
        self.assertIs(farmer.HANDLERS["duty:lead"], queue_mode.plan_lead)
        out = queue_mode.plan_lead({}, ctx(), {"queue": [hitched("07")], "mode": SMUGGLE}, {"needs_help": []})
        self.assertEqual([a["kind"] for a in out], ["smuggle-mode"])


if __name__ == "__main__":
    unittest.main()
