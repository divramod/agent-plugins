"""Hal2 plan 0618 step 1: the reconcile of running delegations (delegation_sync.py, pure) and the round that gathers
its facts once and writes each terminal state once (delegation_round.py)."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import delegation
import delegation_round
import delegation_sync as sync
from test_delegation import MAIN, NOW, Ledger, flaky

START = dt.datetime(2026, 10, 3, 10, 0, tzinfo=dt.timezone.utc)
LATER = START + dt.timedelta(hours=2)


def facts(**over):
    """The facts of one running entry in field 18, started at START, its field known and holding nothing."""
    return {"start": START, "moved_to": None, "taken_by": None, "known": True,
            "field": {"plan": "", "ahead": 0, "created": ""}, "main": {}, **over}


def entry(**over):
    return {"key": "k", "state": "running", "slot": "18", **over}


class Reconcile(unittest.TestCase):
    def judge(self, e=None, now=LATER, **over):
        return sync.reconcile(e or entry(), facts(**over), now)

    def test_a_transplant_runs_on_in_its_target_whatever_the_old_field_shows(self):
        v = self.judge(moved_to="09", field=None)
        self.assertEqual((v["state"], v["slot"], v["from"], v["stop"]), ("running", "09", "18", False))

    def test_a_removed_field_is_gone_and_nothing_is_stopped(self):
        v = self.judge(field=None)
        self.assertEqual((v["state"], v["stop"]), ("gone", False))

    def test_an_unknown_field_list_never_makes_an_entry_gone(self):
        self.assertEqual(self.judge(field=None, known=False)["state"], "landed")  # nothing known: today's rule

    def test_a_newer_delegation_in_the_field_means_this_work_had_ended_and_its_session_is_not_ours(self):
        v = self.judge(taken_by=("brief:newer", START + dt.timedelta(days=1)),
                       field={"plan": "0600-newer", "ahead": 3, "created": ""})
        self.assertEqual((v["state"], v["stop"]), ("landed", False))
        self.assertIn("brief:newer", v["reason"])

    def test_its_recorded_plan_done_on_main_has_landed_and_its_idle_session_stops(self):
        for status in sync.DONE:
            v = self.judge(entry(plan="0500-x"), field={"plan": "0500-x", "ahead": 4}, main={"0500-x": status})
            self.assertEqual((v["state"], v["stop"]), ("landed", True), status)

    def test_its_plan_open_on_main_is_a_milestone_and_still_runs(self):
        v = self.judge(entry(plan="0500-x"), field={"plan": "0500-x", "ahead": 4}, main={"0500-x": "open"})
        self.assertEqual(v["state"], "running")
        self.assertNotIn("plan", v)  # recorded already

    def test_a_field_holding_another_plan_is_moved(self):
        v = self.judge(entry(plan="0500-x"), field={"plan": "0510-other", "ahead": 1})
        self.assertEqual((v["state"], v["stop"]), ("moved", False))

    def test_a_task_name_before_the_plan_exists_is_neither_recorded_nor_compared(self):
        self.assertEqual(self.judge(entry(plan="0500-x"), field={"plan": "fix-the-thing", "ahead": 1})["state"],
                         "running")
        v = self.judge(field={"plan": "fix-the-thing", "ahead": 0})
        self.assertEqual(v["state"], "running")
        self.assertNotIn("plan", v)

    def test_the_first_plan_seen_is_recorded_on_the_running_entry(self):
        v = self.judge(field={"plan": "0500-x", "ahead": 2, "created": "2026-10-03"})
        self.assertEqual((v["state"], v["plan"]), ("running", "0500-x"))

    def test_a_legacy_entry_takes_the_fields_plan_done_on_main_as_landed(self):
        v = self.judge(field={"plan": "0500-x/2", "ahead": 2, "created": "2026-10-03"}, main={"0500-x": "done"})
        self.assertEqual((v["state"], v["stop"]), ("landed", True))

    def test_a_legacy_entry_whose_field_plan_started_days_later_is_moved(self):
        v = self.judge(field={"plan": "0510-later", "ahead": 2, "created": "2026-10-06"}, main={"0510-later": "done"})
        self.assertEqual(v["state"], "moved")
        self.assertEqual(self.judge(field={"plan": "0510-x", "ahead": 2, "created": "2026-10-04"})["state"],
                         "running", "the next day is still its own (a start late in the evening)")

    def test_todays_rule_lands_a_settled_empty_field_and_waits_while_young(self):
        self.assertEqual(self.judge()["state"], "landed")
        self.assertEqual(self.judge(now=START + dt.timedelta(minutes=10))["state"], "running")
        self.assertEqual(self.judge(field={"plan": "", "ahead": 2})["state"], "running")


class Starts(unittest.TestCase):
    def test_a_field_is_entered_on_the_first_note_a_move_and_a_restart_never_on_a_plan_note(self):
        lines = [{"at": "2026-10-03T10:00:00Z", "key": "a", "state": "waiting"},
                 {"at": "2026-10-03T10:05:00Z", "key": "a", "state": "running", "slot": "18"},
                 {"at": "2026-10-03T11:00:00Z", "key": "a", "state": "running", "slot": "18", "plan": "0500-x"},
                 {"at": "2026-10-03T12:00:00Z", "key": "a", "state": "running", "slot": "09", "from": "18"},
                 {"at": "2026-10-03T13:00:00Z", "key": "a", "state": "landed", "slot": "09"},
                 {"at": "2026-10-04T09:00:00Z", "key": "a", "state": "running", "slot": "09"},
                 {"at": "garbage", "key": "b", "state": "running", "slot": "20"}]
        self.assertEqual([(k, s, at.hour) for k, s, at in sync.starts(lines)],
                         [("a", "18", 10), ("a", "09", 12), ("a", "09", 9)])

    def test_only_a_newer_delegation_still_in_the_field_takes_it(self):
        """2026-11-04: learn:tollman was typed into field 81 by mistake and moved to 83 by hand two minutes later;
        tollman-records still worked in 81."""
        lines = [{"at": "2026-11-04T16:30:19Z", "key": "old", "state": "running", "slot": "81"},
                 {"at": "2026-11-04T21:07:44Z", "key": "wrong", "state": "running", "slot": "81"},
                 {"at": "2026-11-04T21:09:26Z", "key": "wrong", "state": "running", "slot": "83"}]
        found = sync.entry_facts("old", lines[0], {"starts": sync.starts(lines), "transplants": [], "known": True,
                                                   "fields": {}, "main": {}})
        self.assertIsNone(found["taken_by"])
        lines.append({"at": "2026-11-05T08:00:00Z", "key": "new", "state": "running", "slot": "81"})
        found = sync.entry_facts("old", lines[0], {"starts": sync.starts(lines), "transplants": [], "known": True,
                                                   "fields": {}, "main": {}})
        self.assertEqual(found["taken_by"][0], "new")

    def test_plan_slug_reads_only_numbered_plans(self):
        self.assertEqual(sync.plan_slug("0618-delegation-ledger-sync\n"), "0618-delegation-ledger-sync")
        self.assertEqual(sync.plan_slug("0349-ci/30"), "0349-ci")
        for text in ("", None, "shots/3/title", "fix-the-thing"):
            self.assertEqual(sync.plan_slug(text), "", text)


class Round(Ledger):
    """delegation.follow_up through the round: one git grep, one transplants call, each terminal state written once."""

    def setUp(self):
        super().setUp()
        self.grep = ""
        base = delegation.call

        def call(argv, cwd):
            if argv[:2] == ["git", "grep"]:
                self.calls.append(argv)
                return 0, self.grep
            return base(argv, cwd)
        p = mock.patch.object(delegation, "call", call)
        p.start()
        self.addCleanup(p.stop)

    def field(self, plan):
        d = Path(tempfile.mkdtemp())
        (d / "plans" / plan).mkdir(parents=True)
        (d / "plans" / plan / "plan.md").write_text(f"---\nid: 1\nstatus: open\ncreated: 2026-10-03\n---\n")
        return str(d)

    def stops(self):
        return [c for c in self.calls if c[:len(delegation.STOP)] == delegation.STOP]

    def log(self):
        return [json.loads(x) for x in (self.tmp / "hal2" / "log.jsonl").read_text().splitlines()]

    def test_main_plans_reads_each_plan_status_once(self):
        out = ("origin/main:plans/0500-x/plan.md:status: done\norigin/main:plans/0500-x/plan.md:status: later\n"
               "origin/main:plans/_archive/0100-y/plan.md:status: \"shipped\"\nnoise\n")
        found = delegation_round.main_plans(MAIN, lambda argv, cwd: (0, out))
        self.assertEqual(found, {"0500-x": "done", "0100-y": "shipped"})
        self.assertEqual(delegation_round.main_plans(MAIN, lambda argv, cwd: (128, out)), {})

    def test_a_landed_plan_on_main_lands_the_entry_once_with_one_log_line(self):
        delegation.delegate(flaky(), MAIN, 5, False, NOW)
        slots = {"18": {"plan": "0500-x", "ahead": 3, "path": self.field("0500-x")}}
        self.assertEqual(delegation.follow_up(MAIN, slots, 5, False, NOW + dt.timedelta(hours=1)), [])
        self.assertEqual(delegation.ledger(MAIN)["flaky:t"]["plan"], "0500-x")
        self.grep = "origin/main:plans/0500-x/plan.md:status: done\n"
        later = NOW + dt.timedelta(hours=3)
        done = delegation.follow_up(MAIN, slots, 5, False, later)
        self.assertEqual([(d["state"], d["slot"]) for d in done], [("landed", "18")])
        self.assertEqual(self.stops(), [delegation.STOP + ["18", "--repo", MAIN]])
        self.assertEqual(delegation.follow_up(MAIN, slots, 5, False, later + dt.timedelta(hours=1)), [])
        self.assertEqual([e["kind"] for e in self.log()], ["delegate", "landed"])
        self.assertEqual(len([c for c in self.calls if c[:2] == ["git", "grep"]]), 2, "one grep per round with work")

    def test_a_field_reused_for_another_plan_is_moved_and_nothing_stopped(self):
        delegation.delegate(flaky(), MAIN, 5, False, NOW)
        delegation.follow_up(MAIN, {"18": {"plan": "0500-x", "ahead": 1}}, 5, False, NOW + dt.timedelta(hours=1))
        done = delegation.follow_up(MAIN, {"18": {"plan": "0510-y", "ahead": 1}}, 5, False, NOW + dt.timedelta(hours=2))
        self.assertEqual([d["state"] for d in done], ["moved"])
        self.assertEqual(self.stops(), [])
        self.assertEqual(delegation.ledger(MAIN)["flaky:t"]["state"], "moved")
        self.assertEqual([e["kind"] for e in self.log()], ["delegate", "moved"])

    def test_a_removed_field_is_gone_once_and_a_waiting_brief_takes_the_room(self):
        delegation.delegate(flaky(), MAIN, 1, False, NOW)
        second = dict(flaky(), key="flaky:u", text="disable u")
        self.assertEqual(delegation.delegate(second, MAIN, 1, False, NOW)["state"], "waiting")
        done = delegation.follow_up(MAIN, {"07": {"plan": "", "ahead": 0}}, 1, False, NOW + dt.timedelta(hours=2))
        self.assertEqual([(d["key"], d["state"]) for d in done], [("flaky:t", "gone"), ("flaky:u", "running")])
        self.assertEqual(self.stops(), [])

    def test_a_dry_round_reports_and_writes_nothing(self):
        delegation.delegate(flaky(), MAIN, 5, False, NOW)
        before = delegation.lines(MAIN)
        done = delegation.follow_up(MAIN, {"07": {"plan": "", "ahead": 0}}, 5, True, NOW + dt.timedelta(hours=2))
        self.assertEqual([d["state"] for d in done], ["gone"])
        self.assertEqual(delegation.lines(MAIN), before)


class Working(unittest.TestCase):
    """D6: only a running entry whose field is unpaused and holds a live session uses capacity."""

    PATHS = {"01": "/f/01", "02": "/f/02", "03": "/f/03"}
    ENTRIES = [entry(key="a", slot="01"), entry(key="b", slot="02"), entry(key="c", slot="03")]

    def count(self, sessions, paused=None, paths=None):
        facts = {"sessions": sessions, "paused": paused or {}, "paths": self.PATHS if paths is None else paths}
        return [e["key"] for e in sync.working(self.ENTRIES, facts)]

    def agent(self, path, state="idle"):
        return {"checkout": path, "state": state, "pane_id": "%1"}

    def test_a_field_with_a_live_session_works_whatever_the_state(self):
        sessions = [self.agent("/f/01", "idle"), self.agent("/f/02", "working"), self.agent("/f/03", "sleeping")]
        self.assertEqual(self.count(sessions), ["a", "b", "c"])

    def test_a_field_without_a_session_or_with_an_ended_one_does_not_work(self):
        sessions = [self.agent("/f/01"), self.agent("/f/03", "ended")]
        self.assertEqual(self.count(sessions), ["a"])

    def test_a_paused_field_does_not_work_even_with_a_session(self):
        sessions = [self.agent(p) for p in self.PATHS.values()]
        self.assertEqual(self.count(sessions, paused={"02": {"by": "farmer"}}), ["a", "c"])

    def test_an_unreadable_session_list_counts_every_entry(self):
        self.assertEqual(self.count(None), ["a", "b", "c"])
        self.assertEqual(self.count(None, paused={"02": {}}), ["a", "c"],
                         "a pause is known, the session list is not: only the pause removes an entry")

    def test_a_field_whose_path_is_unknown_counts(self):
        self.assertEqual(self.count([], paths={"01": "/f/01"}), ["b", "c"])
        self.assertEqual(self.count([]), [])


class Limit(Ledger):
    """The foreman limit counts the working foremen (plan 0618 D6). Four foremen run in 01-04, the limit is 2, one
    brief waits."""

    def setUp(self):
        super().setUp()
        self.slots = {f"0{i}": {"plan": f"050{i}-x", "ahead": 1, "path": f"/f/0{i}"} for i in range(1, 5)}
        for i in range(1, 5):
            delegation.note(MAIN, {"key": f"k{i}", "state": "running", "slot": f"0{i}", "title": "t",
                                   "plan": f"050{i}-x"}, NOW)
        delegation.note(MAIN, {"key": "w", "state": "waiting", "brief": "/b/w.md", "title": "waits"}, NOW)
        self.started = []

        def start(prompt, main, dry, values=None):
            self.started.append(prompt)
            return {"slot": "09"}
        for p in (mock.patch.object(delegation, "start", start),
                  mock.patch.object(delegation, "write_role", lambda *a, **k: Path("/b/role.md"))):
            p.start()
            self.addCleanup(p.stop)

    def run_round(self, limit=2):
        return delegation.follow_up(MAIN, self.slots, limit, False, NOW + dt.timedelta(minutes=5))

    def sessions_in(self, *fields):
        return [{"checkout": f"/f/{f}", "state": "idle", "pane_id": f"%{f}"} for f in fields]

    def test_every_running_foreman_with_a_session_counts_and_the_brief_waits(self):
        self.sessions = self.sessions_in("01", "02", "03", "04")
        self.assertEqual(self.run_round(), [])
        self.assertEqual(delegation.ledger(MAIN)["w"]["state"], "waiting")

    def test_paused_and_sessionless_fields_free_the_room_and_the_brief_starts(self):
        self.sessions = self.sessions_in("01", "02", "03")  # 04 has no session
        self.paused = {"03": {"by": "user"}, "02": {"by": "user"}}  # 01 is the only one that works
        done = self.run_round()
        self.assertEqual([(d["key"], d["state"]) for d in done], [("w", "running")])
        self.assertEqual(len(self.started), 1)
        self.assertEqual([e["state"] for k, e in delegation.ledger(MAIN).items() if k.startswith("k")],
                         ["running"] * 4, "the paused and sessionless entries stay running, no terminal state")

    def test_the_brief_starts_only_as_far_as_the_room_goes(self):
        delegation.note(MAIN, {"key": "w2", "state": "waiting", "brief": "/b/w2.md", "title": "waits too"}, NOW)
        self.sessions = self.sessions_in("01")
        self.paused = {"02": {}, "03": {}}  # 01 works, 04 has no session: 1 of limit 2, so one starts
        done = self.run_round(2)
        self.assertEqual([d["state"] for d in done], ["running"])
        self.assertEqual(len(self.started), 1)
        self.assertEqual(delegation.ledger(MAIN)["w2"]["state"], "waiting")

    def test_an_unreadable_session_list_counts_every_running_entry(self):
        self.sessions = None
        self.assertEqual(self.run_round(), [])
        self.assertEqual(self.started, [])

    def test_nothing_is_read_for_auto_or_when_nothing_runs(self):
        with mock.patch.object(delegation_round.live_sessions, "read", side_effect=AssertionError("read")):
            self.assertIsNone(delegation_round.capacity(MAIN, self.slots, "auto"))
            self.assertEqual(delegation_round.capacity("/x/other", self.slots, 2), 0)

    def test_a_new_delegation_of_the_tick_gets_the_working_count(self):
        self.sessions = self.sessions_in("01")
        self.paused = {"02": {}, "03": {}}
        busy = delegation_round.capacity(MAIN, self.slots, 2)
        self.assertEqual(busy, 1)
        for k, e in delegation.ledger(MAIN).items():  # older waiters would start first (row 25): none wait here
            if e.get("state") == "waiting":
                delegation.note(MAIN, {"key": k, "state": "landed"}, NOW)
        a = dict(flaky(), key="flaky:new")
        self.assertEqual(delegation.delegate(a, MAIN, 2, False, NOW, busy=busy)["state"], "running")
        self.assertEqual(delegation.delegate(dict(a, key="flaky:more"), MAIN, 2, False, NOW, busy=busy + 1)["state"],
                         "waiting")


if __name__ == "__main__":
    unittest.main()
