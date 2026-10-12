import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import boss
import deliver
import mtm_scan
import tick

NOW = dt.datetime(2026, 10, 3, 10, 0)


def at(minutes_ago: int) -> str:
    return (NOW - dt.timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


def wt(slot, state: str | None = "done", **kw):
    return {"slot": slot, "path": f"/x/{slot}", "ahead": 1, "plan": "", "agent_state": state, "pane": f"%{slot}", **kw}


def snap(findings, queue=(), worktrees=(), landings=(), priority=None):
    return {"findings": list(findings), "queue": list(queue), "worktrees": list(worktrees),
            "landings": list(landings), "priority": priority}


def plan(s, log=(), main="/x/hal2"):
    planned = boss.plan(s, {"now": NOW, "log": list(log), "main": main})
    return [(a["do"], a["kind"], a["slot"]) for a in tick.fresh(planned, list(log), NOW)]


HELD = {"kind": "held-idle", "slot": "04", "why": "held", "failure": "test-unit hal2-macos"}
Q = [{"slot": "04", "state": "held", "seq": 7, "landing": "L1"}, {"slot": "05", "state": "waiting", "seq": 8}]


class Held(unittest.TestCase):
    def test_a_holder_with_a_session_is_woken_hourly_and_never_released(self):
        # The user, 2026-10-06: "run landing until everything is fixed and merged and then release".
        s = snap([HELD], Q, [wt("04"), wt("05")])
        self.assertEqual(plan(s), [("send", "held-idle", "04")])
        woke = [{"at": at(20), "key": "wake:04:7", "kind": "held-idle"}]
        self.assertEqual(plan(s, woke), [], "no release after a wake")
        woke[0]["at"] = at(70)
        self.assertEqual(plan(s, woke), [("send", "held-idle", "04")], "woken again after an hour")
        reserved = snap([dict(HELD, kind="reserved-idle")], Q, [wt("04", state="sleeping"), wt("05")])
        self.assertEqual(plan(reserved), [("send", "reserved-idle", "04")])

    def test_a_holder_whose_session_ended_is_released_and_the_waiters_told(self):
        s = snap([HELD], Q, [wt("04", state="ended"), wt("05")])
        self.assertEqual(plan(s), [("run", "release", "04"), ("send", "released", "04"), ("send", "moves", "05")])
        released = [{"at": at(1), "key": "release:04:7"}, {"at": at(1), "key": "released:04:7"},
                    {"at": at(1), "key": "moves:04:7:05"}]
        self.assertEqual(plan(s, released), [])

    def test_a_holder_without_session_is_released_at_once(self):
        s = snap([dict(HELD, kind="reserved-idle")], Q, [wt("04", state=None), wt("05")])
        self.assertEqual(plan(s)[0], ("run", "release", "04"))


LEAD = {"slot": "02", "plan": "0149-hal9k", "step": "7"}


class Subservant(unittest.TestCase):
    """Skills plan 0013: a slot with plans/LEAD never lands, so it never gets the /mtm text."""

    def test_a_subservant_holding_the_queue_wakes_the_farmer(self):
        f = {"kind": "subservant-holds", "slot": "31", "seq": 7, "lead": LEAD, "why": "subservant of slot 02"}
        s = snap([f], [{"slot": "31", "state": "held", "seq": 7}], [wt("31", lead=LEAD)])
        self.assertEqual(plan(s), [("wake", "subservant-holds", "31")])
        self.assertEqual(plan(s, [{"at": at(30), "key": "subservant-holds:31"}]), [], "at most hourly")

    def test_a_landing_finding_for_a_marked_slot_never_sends_mtm_or_releases(self):
        q = [{"slot": "31", "state": "held", "seq": 7}, {"slot": "32", "state": "waiting", "seq": 8}]
        for state in ("sleeping", "ended", None):
            found = [dict(HELD, slot="31"), dict(HELD, slot="31", kind="reserved-idle"),
                     {"kind": "waiter-gone", "slot": "32", "why": ""}]
            s = snap(found, q, [wt("31", state=state, lead=LEAD), wt("32", lead=LEAD)])
            planned = boss.plan(s, {"now": NOW, "log": [], "main": "/x/hal2"})
            self.assertEqual({(a["do"], a["kind"]) for a in planned}, {("wake", "subservant-holds")}, state)
            self.assertNotIn("/mtm", json.dumps(planned))
            self.assertIn("subservant of slot 02 (plan 0149-hal9k step 7)", planned[0]["text"])


class Queue(unittest.TestCase):
    def test_priority_never_reranks_and_is_done_when_landed(self):
        q = [{"slot": "01", "state": "waiting", "seq": 1}, {"slot": "04", "state": "waiting", "seq": 2}]
        f = {"kind": "priority", "slot": "04", "why": ""}
        self.assertEqual(plan(snap([f], q, [wt("04")], priority={"slots": ["04"]})), [], "hal2 keeps the order")
        self.assertEqual(plan(snap([f], [], [wt("04")], priority={"slots": ["04"]})), [], "no land-now tell")
        done = snap([f], [], [wt("04", ahead=0)], [{"slot": "04", "outcome": "landed", "tests": []}])
        planned = boss.plan(done, {"now": NOW, "log": [], "main": "/x/hal2"})
        self.assertEqual([(a["do"], a["kind"]) for a in planned], [("run", "priority-done"), ("notify", "priority-done")])
        self.assertEqual(planned[0]["argv"][2:5], ["priority", "--done", "04"])

    def test_a_waiting_reservation_tells_the_user_every_six_hours(self):
        f = {"kind": "reservation-waits", "slot": "18", "seq": 9, "why": "the queue waits"}
        s = snap([f], [{"slot": "18", "state": "waiting", "seq": 9}], [wt("18")])
        self.assertEqual(plan(s), [("notify", "reservation-waits", "18")])
        self.assertEqual(plan(s, [{"at": at(120), "key": "reservation-waits:18:9"}]), [])
        self.assertEqual(plan(s, [{"at": at(7 * 60), "key": "reservation-waits:18:9"}]),
                         [("notify", "reservation-waits", "18")])

    def test_pause_busy_slots_during_a_landing_and_go_after_it(self):
        q = [{"slot": "04", "state": "active", "seq": 7, "landing": "L1"}]
        f = {"kind": "load-high", "slot": "04", "why": "", "busy_slots": ["08"]}
        self.assertEqual(plan(snap([f], q, [wt("08", "working")])), [("send", "pause", "08")])
        paused = [{"at": at(30), "key": "pause:L1:08"}]
        self.assertEqual(plan(snap([f], q, [wt("08")]), paused), [])
        self.assertEqual(plan(snap([], [], [wt("08")]), paused), [("send", "go", "08")])
        self.assertEqual(plan(snap([], [], [wt("08")]), paused + [{"at": at(1), "key": "go:L1:08"}]), [])

    def test_a_gone_waiter_is_told_once_in_two_hours(self):
        f = {"kind": "waiter-gone", "slot": "05", "why": ""}
        s = snap([f], Q, [wt("05")])
        self.assertEqual(plan(s), [("send", "waiter-gone", "05")])
        self.assertEqual(plan(s, [{"at": at(60), "key": "waiter:05:8"}]), [])


class Work(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(mtm_scan, "DATA", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def test_flaky_under_load_is_delegated_unclear_wakes_ledgered_is_left(self):
        f = {"kind": "flaky-candidate", "slot": "08", "why": "t failed 3x", "test": "t"}
        hinted = [{"slot": "08", "outcome": "failed", "tests": ["t"], "load_hint": True}]
        self.assertEqual(plan(snap([f], landings=hinted)), [("delegate", "flaky", "08")])
        plain = [dict(hinted[0], load_hint=False)]
        self.assertEqual(plan(snap([f], landings=plain)), [("wake", "flaky", "08")])
        (self.tmp / "hal2").mkdir(exist_ok=True)
        (self.tmp / "hal2" / "flaky.md").write_text("- 2026-10-03 t disabled\n")
        self.assertEqual(plan(snap([f], landings=hinted)), [])

    def test_orphans_with_a_handoff_get_a_session_others_wake_asked_ones_wait(self):
        (self.tmp / "11").mkdir()
        (self.tmp / "11" / "HANDOFF.md").write_text("x")
        f = {"kind": "work-without-agent", "slot": "11", "why": ""}
        w = wt("11", state=None, plan="0085-x", path=str(self.tmp / "11"))
        self.assertEqual(plan(snap([f], [], [w])), [("run", "orphan", "11")])
        self.assertEqual(plan(snap([f], [], [dict(w, path="/nowhere")])), [("wake", "orphan", "11")])
        asked = [{"at": at(60), "kind": "ask", "slot": "11"}]
        self.assertEqual(plan(snap([f], [], [w]), asked), [])
        answered = asked + [{"at": at(5), "kind": "answered", "slot": "11"}]
        self.assertEqual(plan(snap([f], [], [w]), answered), [("run", "orphan", "11")])

    def test_an_orphan_with_only_its_plans_own_handoff_gets_a_session(self):
        # hal2 plan 0206: a plan in the record format keeps its handoff in its folder, committed.
        folder = self.tmp / "12" / "plans" / "0085-x"
        folder.mkdir(parents=True)
        f = {"kind": "work-without-agent", "slot": "12", "why": ""}
        w = wt("12", state=None, plan="0085-x", path=str(self.tmp / "12"))
        self.assertEqual(plan(snap([f], [], [w])), [("wake", "orphan", "12")])
        (folder / "handoff.md").write_text("x")
        self.assertEqual(plan(snap([f], [], [w])), [("run", "orphan", "12")])
        self.assertEqual(plan(snap([f], [], [dict(w, plan="shooter/1/x")])), [("wake", "orphan", "12")])

    def test_a_marked_orphan_is_restarted_only_with_handoff_c_else_wakes(self):
        # Skills plan 0013: a subservant (plans/LEAD) continues its one step, never lands.
        (self.tmp / "31").mkdir()
        (self.tmp / "31" / "HANDOFF.md").write_text("x")
        f = {"kind": "work-without-agent", "slot": "31", "why": "", "lead": LEAD}
        w = wt("31", state=None, lead=LEAD, path=str(self.tmp / "31"), missing=["HEAD: 1 commit(s) not in origin/02"])
        planned = boss.plan(snap([f], [], [w]), {"now": NOW, "log": [], "main": "/x/hal2"})
        self.assertEqual([(a["do"], a["kind"]) for a in planned], [("run", "orphan")])
        self.assertEqual(planned[0]["argv"][-2:], ["--prompt", "/handoff c"])
        bare = boss.plan(snap([f], [], [dict(w, path="/nowhere")]), {"now": NOW, "log": [], "main": "/x/hal2"})
        self.assertEqual([(a["do"], a["kind"]) for a in bare], [("wake", "orphan")])
        self.assertNotIn("/mtm", json.dumps(planned + bare))

    def test_a_marked_orphan_merged_into_its_lead_is_not_restarted_a_broken_marker_wakes(self):
        # Review 1 findings 3 and 10: nothing missing in origin/<lead> means its step is done; a broken marker
        # names no lead, so the farmer judges it.
        (self.tmp / "31").mkdir()
        (self.tmp / "31" / "HANDOFF.md").write_text("x")
        f = {"kind": "work-without-agent", "slot": "31", "why": "", "lead": LEAD}
        merged = wt("31", state=None, lead=LEAD, path=str(self.tmp / "31"), missing=[], ahead=5)
        self.assertEqual(plan(snap([f], [], [merged])), [])
        bad = {"bad": True, "text": "x", "error": "plans/LEAD is not `<lead-slot> <plan> <step>`: 'x'"}
        broken = dict(merged, lead=bad, missing=[bad["error"], "HEAD: 5 commit(s) not in origin/main"])
        self.assertEqual(plan(snap([dict(f, lead=bad)], [], [broken])), [("wake", "orphan", "31")])

    def test_judgment_kinds_wake_at_most_hourly(self):
        f = {"kind": "long-queue", "slot": "01,02,03", "why": "3 waiting"}
        self.assertEqual(plan(snap([f])), [("wake", "long-queue", "01,02,03")])
        self.assertEqual(plan(snap([f]), [{"at": at(30), "key": "long-queue:01,02,03"}]), [])




class Prompt(unittest.TestCase):
    def test_send_asks_hal2_to_type_only_into_an_empty_box(self):
        self.assertEqual(
            deliver.if_empty("%8", "hi"), ["send", "%8", "hi", "--paste", "--if-empty", "--submit"])
        self.assertEqual(deliver.if_empty("%8", "hi", deliver.READY | {"failed"})[-2:], ["--allow-state", "failed"])
        err = 'hal2-cli-agents: not sent: draft: the input box holds "my draft"\n'
        self.assertEqual(deliver.refusal(err), 'draft: the input box holds "my draft"')

    def test_send_submits_in_one_call_and_reports_a_text_not_taken(self):
        err = "hal2-cli-agents: not submitted: not-taken: the session did not take the text after two Enters; " \
            "hal2's text was removed, the box is empty\n"
        with mock.patch.object(deliver, "run", return_value=(4, "", err)) as run:
            why = deliver.send("%8", "hi")
        self.assertEqual(run.call_count, 1, "no separate Enter")
        self.assertTrue(why.startswith("not-taken: "), why)
        with mock.patch.object(deliver, "run", return_value=(0, "", "")) as run:
            self.assertIsNone(deliver.send("%8", "hi"))
        self.assertEqual(run.call_count, 1)

    def test_send_falls_back_for_a_cli_without_submit(self):
        usage = "hal2-cli-agents: send takes <pane> <text> [--key | --paste] [--if-empty [--allow-state <state>]...]\n"
        calls = []

        def run(*args, timeout=30):
            calls.append(args)
            return (1, "", usage) if "--submit" in args else (0, "", "")

        with mock.patch.object(deliver, "run", side_effect=run):
            self.assertIsNone(deliver.send("%8", "hi"))
        self.assertEqual(calls[1], ("send", "%8", "hi", "--paste", "--if-empty"))
        self.assertEqual(calls[2], ("send", "%8", "enter", "--key"))

    def test_a_refused_send_becomes_a_relay(self):
        out = {"wake": [], "notify": []}
        a = tick.act("mtm", "pause", "send", "08", pane="%8", text="pause", key="pause:L1:08")
        with mock.patch.object(deliver, "send", return_value="agent is working"), \
                mock.patch.object(mtm_scan, "log") as log:
            tick.execute(a, "/x/farmer", "/x/hal2", out)
        self.assertEqual([r["kind"] for r in out["relay"]], ["pause"])
        self.assertEqual(log.call_args.args[1]["do"], "relay")
        self.assertIn("agent is working", log.call_args.args[1]["note"])


if __name__ == "__main__":
    unittest.main()
