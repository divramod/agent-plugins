import datetime as dt
import json
import unittest
from unittest import mock

import tick
import wake
from test_farmer import NOW, Repo

AGENTS = json.dumps([{"pane_id": "%9", "checkout": "/x/wt/farmer", "state": "idle"}])


def judgment(text="07 asks which API to keep"):
    return tick.act("lead", "question", "wake", "07", text=text, evidence={"question": text})


class Wake(Repo):
    """hand_over against a fake send: what the farmer session gets and how often it is woken."""

    def setUp(self):
        super().setUp()
        self.sent, self.refuse = [], None

        def send(pane, text, states=None):
            if self.refuse:
                return self.refuse
            self.sent.append((pane, text))
            return None

        for p in (mock.patch.object(wake.deliver, "send", send),
                  mock.patch.object(wake, "farmer_pane", return_value="%9")):
            p.start()
            self.addCleanup(p.stop)
        self.main = str(self.main)

    def over(self, out, at=NOW):
        return wake.hand_over("/x/wt/farmer", self.main, out, at)

    def test_nothing_to_judge_adds_no_turn_and_no_file(self):
        r = self.over({"wake": [], "notify": [], "relay": [], "delegations": [{"state": "running"}]})
        self.assertEqual((r["woken"], self.sent), (False, []))
        self.assertFalse(wake.wake_file(self.main).exists())

    def test_a_judgment_item_wakes_once_until_it_is_handled(self):
        self.assertTrue(self.over({"wake": [judgment()]})["woken"])
        self.assertEqual(self.sent, [("%9", "/farmer act")])
        self.over({})
        notice = tick.act("frame", "role-invalid", "notify", text="bad role")
        self.over({"notify": [notice]}, NOW + dt.timedelta(minutes=15))
        self.assertEqual(len(self.sent), 1)
        items = wake.read(self.main)["items"]
        self.assertEqual([(i["seq"], i["kind"]) for i in items], [(1, "question"), (2, "role-invalid")])
        self.assertEqual(items[0]["instructions"], wake.instructions("lead", "question"))
        self.assertEqual(items[0]["evidence"], {"question": "07 asks which API to keep"})
        self.assertEqual(wake.done(self.main, 1), 1)
        self.over({}, NOW + dt.timedelta(minutes=30))
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(wake.done(self.main, 2), 0)
        self.assertFalse(wake.wake_file(self.main).exists())

    def test_a_refused_wake_is_retried_and_a_forgotten_one_repeated(self):
        self.refuse = "agent is working"
        self.assertEqual(self.over({"wake": [judgment()]})["why"], "agent is working")
        self.refuse = None
        self.assertTrue(self.over({})["woken"])
        self.over({}, NOW + dt.timedelta(minutes=50))
        self.assertEqual(len(self.sent), 1)
        self.over({}, NOW + dt.timedelta(minutes=70))
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(sum(e["kind"] == "wake" for e in self.log()), 2)

    def test_relays_and_failed_delegations_are_handed_over(self):
        relay = tick.act("mtm", "front", "relay", "07", text="land now", why="not typed: agent is working")
        failed = {"key": "flaky:t", "state": "error", "title": "disable t", "error": "create.py failed"}
        self.over({"relay": [relay], "delegations": [failed, {"state": "running"}]})
        items = wake.read(self.main)["items"]
        self.assertEqual([(i["do"], i["kind"]) for i in items], [("relay", "front"), ("wake", "delegate-failed")])
        self.assertEqual(items[1]["evidence"]["error"], "create.py failed")
        self.assertEqual(items[1]["instructions"], wake.instructions("farmer", "delegate-failed"))


class Handoff(Repo):
    """The farmer's context: below CLEAR_AT a plain wake, from it the handoff, which holds other wakes back until
    the farmer pane shows its new session or HANDOFF_TIMEOUT falls back to a plain /clear."""

    def setUp(self):
        super().setUp()
        self.sent, self.agent = [], {"context_percent": 5, "session_id": "a", "state": "idle"}

        def send(pane, text, states=None):
            self.sent.append(text)
            if text == "/clear":
                self.agent = {"context_percent": 0, "session_id": "c", "state": "idle"}

        for p in (mock.patch.object(wake.deliver, "send", send),
                  mock.patch.object(wake.deliver, "agent", lambda pane: dict(self.agent)),
                  mock.patch.object(wake, "farmer_pane", return_value="%9"),
                  mock.patch.object(wake.time, "sleep", lambda s: None)):
            p.start()
            self.addCleanup(p.stop)
        self.main = str(self.main)

    def over(self, out, minutes=0):
        return wake.hand_over("/x/wt/farmer", self.main, out, NOW + dt.timedelta(minutes=minutes))

    def test_below_the_threshold_a_plain_wake(self):
        self.agent["context_percent"] = wake.CLEAR_AT - 1
        self.assertTrue(self.over({"wake": [judgment()]})["woken"])
        self.assertEqual(self.sent, ["/farmer act"])

    def test_from_the_threshold_the_handoff_no_clear_and_no_double_wake(self):
        self.agent["context_percent"] = wake.CLEAR_AT
        r = self.over({"wake": [judgment()]})
        self.assertEqual((r["woken"], r["why"], self.sent), (False, "handoff asked", ["/farmer handoff"]))
        self.assertEqual(wake.read(self.main)["handoff"], {"at": NOW.isoformat(timespec="seconds"), "session": "a"})
        for minutes in (5, 14):
            r = self.over({"wake": [judgment("08 asks too")]}, minutes)
            self.assertEqual(r["why"], "handoff under way")
        self.assertEqual(self.sent, ["/farmer handoff"])
        self.assertEqual([e["kind"] for e in self.log()], ["handoff"])

    def test_the_new_session_ends_the_handoff_and_counts_as_the_wake(self):
        self.agent["context_percent"] = 55
        self.over({"wake": [judgment()]})
        self.agent = {"context_percent": 3, "session_id": "b", "state": "working"}
        r = self.over({}, 3)
        self.assertTrue(r["woken"])
        self.assertEqual(self.sent, ["/farmer handoff"])
        data = wake.read(self.main)
        self.assertNotIn("handoff", data)
        self.assertEqual(data["woken_at"], (NOW + dt.timedelta(minutes=3)).isoformat(timespec="seconds"))
        self.over({}, 10)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual([e["kind"] for e in self.log()], ["handoff", "handoff-done", "wake"])

    def test_a_handoff_never_done_falls_back_to_a_plain_clear(self):
        self.agent["context_percent"] = 55
        self.over({"wake": [judgment()]})
        r = self.over({}, 16)
        self.assertTrue(r["woken"])
        self.assertEqual(self.sent, ["/farmer handoff", "/clear", "/farmer act"])
        self.assertNotIn("handoff", wake.read(self.main))
        self.assertIn("handoff-timeout", [e["kind"] for e in self.log()])

    def test_done_ends_a_pending_handoff(self):
        self.agent["context_percent"] = 55
        self.over({"wake": [judgment()], "notify": [tick.act("frame", "x", "notify", text="n")]})
        self.assertEqual(wake.done(self.main, 1), 1)
        self.assertNotIn("handoff", wake.read(self.main))


class Instructions(unittest.TestCase):
    def test_every_duty_has_its_instructions(self):
        for duty in ("mtm", "lead", "ci", "watch", "autoclear", "task", "frame", "farmer"):
            self.assertTrue(wake.instructions(duty, "any").endswith(f"instructions/{duty}.md"), duty)


class Ticks(Repo):
    """Whole rounds: a quiet one wakes nobody, one with a judgment item wakes the farmer session once."""

    def round(self, handlers, sent, at=NOW):
        def cli(*args, timeout=30):
            return 0, AGENTS.replace("/x/wt/farmer", str(self.slot))

        with mock.patch.object(tick, "sh", return_value=(0, '{"status": "ok"}')), \
                mock.patch.object(tick, "summarize"), mock.patch.object(wake.deliver, "cli", cli), \
                mock.patch.object(wake.deliver, "send", lambda p, t, s=None: sent.append((p, t))):
            return tick.run(str(self.slot), False, handlers, at)

    def test_quiet_then_judgment(self):
        sent = []
        quiet = {"duty:mtm": lambda i, c: [tick.act("mtm", "front", "record", "07", text="x")],
                 "task:*": lambda i, c: []}
        r = self.round(quiet, sent)
        self.assertEqual((r["woke"]["pending"], sent), (0, []))
        self.assertFalse(wake.wake_file(str(self.main)).exists())
        r = self.round({"duty:mtm": lambda i, c: [judgment()], "task:*": lambda i, c: []}, sent,
                       NOW + dt.timedelta(minutes=15))
        self.assertEqual((r["woke"]["woken"], sent), (True, [("%9", "/farmer act")]))
        self.assertEqual(r["wake"][0]["kind"], "question")

    def test_a_dry_run_lists_the_items_and_wakes_nobody(self):
        with mock.patch.object(wake.deliver, "send") as send:
            r = tick.run(str(self.slot), True, {"duty:mtm": lambda i, c: [judgment()]}, NOW)
        send.assert_not_called()
        self.assertEqual([i["kind"] for i in r["wake_items"]], ["question", "no-handler"])
        self.assertFalse(wake.wake_file(str(self.main)).exists())


if __name__ == "__main__":
    unittest.main()
