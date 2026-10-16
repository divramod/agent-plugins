import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame
import acks
import boss
import mtm_scan
import roles
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
    """Skills plan 0013: a worktree with plans/LEAD never lands, so it never gets the /mtm text."""

    def test_a_subservant_holding_the_queue_wakes_the_wagon_master(self):
        f = {"kind": "subservant-holds", "slot": "31", "seq": 7, "lead": LEAD, "why": "servant of worktree 02"}
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
            self.assertIn("servant of field 02's plan 0149-hal9k (step 7)", planned[0]["text"])


class Queue(unittest.TestCase):
    def test_priority_never_reranks_and_is_done_when_landed(self):
        q = [{"slot": "01", "state": "waiting", "seq": 1}, {"slot": "04", "state": "waiting", "seq": 2}]
        f = {"kind": "priority", "slot": "04", "why": ""}
        self.assertEqual(plan(snap([f], q, [wt("04")], priority={"slots": ["04"]})), [], "hal2 keeps the order")
        self.assertEqual(plan(snap([f], [], [wt("04")], priority={"slots": ["04"]})), [], "no land-now tell")
        done = snap([f], [], [wt("04", ahead=0)], [{"slot": "04", "outcome": "landed", "tests": []}])
        planned = boss.plan(done, {"now": NOW, "log": [], "main": "/x/hal2"})
        self.assertEqual([(a["do"], a["kind"]) for a in planned], [("run", "priority-done"), ("notify", "priority-done")])
        self.assertEqual(planned[0]["argv"][1:], [str(farmer_frame.SCRIPTS / "mtm_scan.py"), "priority", "--done",
                                                  "04", "--repo", "/x/hal2", "--role", "wagon-master"])
        self.assertEqual(planned[1]["text"], "wagon-master: your priority worktree 04 has landed")
        self.assertTrue((farmer_frame.SCRIPTS / "mtm_scan.py").is_file(), "the scan stays in the farmer skill")
        done_log = [{"at": at(10), "key": "priority-off:04"}, {"at": at(10), "key": "priority-done:04"}]
        self.assertEqual(tick.fresh(planned, done_log, NOW), [], "once an hour")

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
        farmers = self.tmp / "hal2" / "flaky.md"  # the wagon master reads its own ledger, never the farmer's
        farmers.parent.mkdir(exist_ok=True)
        farmers.write_text("- 2026-10-03 t disabled\n")
        self.assertEqual(plan(snap([f], landings=hinted)), [("delegate", "flaky", "08")])
        (self.tmp / "hal2" / "wagon-master").mkdir(exist_ok=True)
        (self.tmp / "hal2" / "wagon-master" / "flaky.md").write_text("- 2026-10-03 t disabled\n")
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
        # Skills plan 0013: a servant (plans/LEAD) continues its one step, never lands.
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
        # Review 1 findings 3 and 10: nothing missing in origin/<foreman> means its step is done; a broken marker
        # names no foreman, so the wagon master judges it.
        (self.tmp / "31").mkdir()
        (self.tmp / "31" / "HANDOFF.md").write_text("x")
        f = {"kind": "work-without-agent", "slot": "31", "why": "", "lead": LEAD}
        merged = wt("31", state=None, lead=LEAD, path=str(self.tmp / "31"), missing=[], ahead=5)
        self.assertEqual(plan(snap([f], [], [merged])), [])
        bad = {"bad": True, "text": "x", "error": "plans/LEAD is not `<lead-slot> <plan> <step>`: 'x'"}
        broken = dict(merged, lead=bad, missing=[bad["error"], "HEAD: 5 commit(s) not in origin/main"])
        self.assertEqual(plan(snap([dict(f, lead=bad)], [], [broken])), [("wake", "orphan", "31")])

    def test_an_orphan_in_an_open_transplant_is_skipped_an_old_one_is_reported(self):
        # Plan 0294 step 15 (D29); the cases are in test_transplant.py.
        (self.tmp / "11").mkdir()
        (self.tmp / "11" / "HANDOFF.md").write_text("x")
        f = {"kind": "work-without-agent", "slot": "11", "why": ""}
        w = wt("11", state=None, plan="0085-x", path=str(self.tmp / "11"))
        since = lambda minutes: (NOW.astimezone() - dt.timedelta(minutes=minutes)).isoformat()
        for ago, expected in ((5, []), (90, [("send", "transplant-stale", "farmer-hal2")])):
            open_one = {"from": "34", "to": "11", "state": "driven", "prepared": since(ago), "id": "t-34-to-11"}
            planned = boss.plan(snap([f], [], [w]), {"now": NOW, "log": [], "main": "/x/hal2",
                                                      "transplants": [open_one]})
            self.assertEqual([(a["do"], a["kind"], a["slot"]) for a in planned], expected)

    def test_judgment_kinds_wake_at_most_hourly(self):
        f = {"kind": "long-queue", "slot": "01,02,03", "why": "3 waiting"}
        self.assertEqual(plan(snap([f])), [("wake", "long-queue", "01,02,03")])
        self.assertEqual(plan(snap([f]), [{"at": at(30), "key": "long-queue:01,02,03"}]), [])


class Home(unittest.TestCase):
    """Hal2 plan 0294 step 5: the boss is the wagon master's. Its messages carry that name, its state is the folder
    of the role the round runs for, and every action it plans carries a key (D22: a keyless action that is held
    makes tick.fresh drop the rest of the list)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(mtm_scan, "DATA", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def everything(self):
        lead = {"slot": "02", "plan": "0149-hal9k", "step": "7"}
        findings = [HELD, {"kind": "priority", "slot": "06", "why": ""},
                    {"kind": "reservation-waits", "slot": "18", "seq": 9, "why": "the queue waits"},
                    {"kind": "load-high", "slot": "04", "why": "", "busy_slots": ["05"]},
                    {"kind": "waiter-gone", "slot": "05", "why": ""},
                    {"kind": "flaky-candidate", "slot": "08", "why": "t failed 3x", "test": "t"},
                    {"kind": "flaky-candidate", "slot": "08", "why": "u failed 3x", "test": "u"},
                    {"kind": "work-without-agent", "slot": "09", "why": "no agent"},
                    {"kind": "subservant-holds", "slot": "31", "why": "holds", "lead": lead},
                    {"kind": "long-queue", "slot": "01,02,03", "why": "3 waiting"},
                    {"kind": "reserved-idle", "slot": "07", "why": "reserved"}]
        landings = [{"slot": "06", "outcome": "landed", "tests": []},
                    {"slot": "08", "outcome": "failed", "tests": ["t"], "load_hint": True}]
        worktrees = [wt("04"), wt("05"), wt("06", ahead=0), wt("07", state=None), wt("08"), wt("09", state=None)]
        log = [{"at": at(30), "key": "pause:L0:05"}]
        return snap(findings, Q, worktrees, landings), log

    def test_every_planned_action_carries_a_key(self):
        s, log = self.everything()
        planned = boss.plan(s, {"now": NOW, "log": log, "main": "/x/hal2"})
        self.assertEqual({a["kind"] for a in planned},
                         {"held-idle", "priority-done", "reservation-waits", "pause", "waiter-gone", "flaky", "orphan",
                          "subservant-holds", "long-queue", "release", "released", "moves", "go"})
        self.assertEqual([a for a in planned if not a.get("key")], [])

    def test_the_messages_are_the_wagon_master_s(self):
        s, log = self.everything()
        planned = boss.plan(s, {"now": NOW, "log": log, "main": "/x/hal2"})
        texts = [a["text"] for a in planned if a["do"] in ("send", "notify")]
        self.assertTrue(texts and all(t.startswith("wagon-master") for t in texts), texts)
        self.assertEqual(acks.stamp(boss.TEXT["go"], "07-1", boss.ROLE).splitlines()[0],
                         "wagon-master [07-1] (merge-to-main boss): go: /continue")

    def test_the_handler_keeps_its_scan_in_the_folder_of_the_round_s_role(self):
        ctx = {"now": NOW, "log": [], "main": "/x/hal2", "top": "/x/wm", "dry": False}
        with mock.patch.object(mtm_scan, "snapshot", return_value=snap([])) as scan:
            self.assertEqual(boss.handler({}, ctx), [])
            self.assertEqual(scan.call_args.kwargs, {"fetch": True, "role": "wagon-master"})
            self.assertTrue((self.tmp / "hal2/wagon-master/last-scan.json").is_file())
            self.assertEqual(sorted(f.name for f in (self.tmp / "hal2").iterdir()), ["wagon-master"])
            lord = roles.Wiring(role="lord", cli=Path("/k/lord.py"), skill=Path("/k"), act="/lord act",
                                handoff="/lord handoff", duties=("mtm",), subskills={})
            boss.handler({}, {**ctx, "wiring": lord, "dry": True})
            self.assertEqual(scan.call_args.kwargs, {"fetch": False, "role": "lord"})


class OneWakePerState(unittest.TestCase):
    """Plan 0333 step 5, cause B: field 00 woke the model five times in one afternoon (13:13 to 17:56 local) at the
    same "49 commits, plan 0253-mobile-app" while its ack 00-1 said it waits for the user's console approval."""

    def finding(self, ahead, plan="0253-mobile-app", slot="00"):
        return {"kind": "work-not-queued", "slot": slot,
                "why": f"{ahead} commits not on main, plan {plan}, agent sleeping for 33 min"}

    def rounds(self, times, ahead_of, ack_at=None, plan="0253-mobile-app", status="refused"):
        """Run a round at each time (day 2026-10-14); a planned wake enters the log as the tick writes it."""
        log, woken = [], []
        for hh, mm in times:
            if ack_at and (hh, mm) > ack_at and not any(e["kind"] == "ack" for e in log):
                log.append({"at": f"2026-10-14T{ack_at[0]}:{ack_at[1]:02d}:43", "kind": "ack", "slot": "00",
                            "what": status, "id": "00-1"})
            now = dt.datetime(2026, 10, 14, hh, mm)
            f = self.finding(ahead_of((hh, mm)), plan)
            planned = boss.plan(snap([f], worktrees=[wt("00", ahead=f["why"].split()[0])]),
                                {"now": now, "log": log, "main": "/x/hal2"})
            for a in tick.fresh(planned, log, now):
                self.assertEqual((a["do"], a["kind"], a["slot"]), ("wake", "work-not-queued", "00"))
                log.append({"at": now.isoformat(timespec="seconds"), "kind": a["kind"], "slot": "00",
                            "what": a["text"], "key": a["key"]})
                woken.append((hh, mm))
        return woken

    TIMES = [(13, 13), (14, 23), (15, 34), (16, 42), (17, 56)]

    def test_a_refused_field_with_no_new_commit_is_woken_once_not_five_times(self):
        self.assertEqual(self.rounds(self.TIMES, lambda t: 49, ack_at=(13, 18)), [(13, 13)])

    def test_a_new_commit_after_the_refusal_wakes_again(self):
        got = self.rounds(self.TIMES, lambda t: 49 if t < (16, 42) else 50, ack_at=(13, 18))
        self.assertEqual(got, [(13, 13), (16, 42)])

    def test_an_unchanged_state_without_a_refusal_wakes_once_a_day_another_plan_wakes_again(self):
        self.assertEqual(self.rounds(self.TIMES, lambda t: 49), [(13, 13)])
        self.assertEqual(self.rounds(self.TIMES, lambda t: 49, ack_at=(13, 18), status="started"), [(13, 13)])
        s = snap([self.finding(49)], worktrees=[wt("00", ahead=49)])
        woke = [{"at": at(23 * 60), "key": "work-not-queued:00:49:0253-mobile-app"}]
        self.assertEqual(plan(s, woke), [], "less than a day ago")
        woke[0]["at"] = at(25 * 60)
        self.assertEqual(plan(s, woke), [("wake", "work-not-queued", "00")], "a day later")
        other = snap([self.finding(49, "0301-other")], worktrees=[wt("00", ahead=49)])
        woke[0]["at"] = at(5)
        self.assertEqual(plan(other, woke), [("wake", "work-not-queued", "00")], "another plan")

    def test_the_other_judgment_kinds_still_wake_hourly(self):
        s = snap([{"kind": "long-queue", "slot": "04,05,06", "why": "3 waiting"}])
        self.assertEqual(plan(s), [("wake", "long-queue", "04,05,06")])
        self.assertEqual(plan(s, [{"at": at(70), "key": "long-queue:04,05,06"}]), [("wake", "long-queue", "04,05,06")])
        self.assertEqual(plan(s, [{"at": at(30), "key": "long-queue:04,05,06"}]), [])


if __name__ == "__main__":
    unittest.main()
