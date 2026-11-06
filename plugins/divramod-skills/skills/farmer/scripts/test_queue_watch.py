"""Hal2 plan 0570 step 5 (D8): the merge-queue watch as a farmer tick duty (queue_watch.py). Every finding from a fixture
queue, a healthy queue none, the first-seen time carried across ticks, a finding past 30 min alarmed once (STALLED-GATE
as `runner-down`, the others push-only cases), the state file's schema, a dry round writing nothing, and the CLI's
lines and exits. Never the real queue (a faked runner), never a real alarm or notice (the alarm is a planned act)."""

import contextlib
import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer
import mtm_scan
import queue_watch as qw
import roles

NOW = dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.timezone.utc)


def ago(minutes: float, now: dt.datetime = NOW) -> str:
    return (now - dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ticket(slot: str, **fields) -> dict:
    return {"repo": "hal2", "slot": slot, "pid": 0, "enqueued": ago(5), "hold": None, "reserved": None,
            "harvest": None, **fields}


def harvest(started: float, step_started: float, outcome: str = "running", finished=None) -> dict:
    return {"outcome": outcome, "finished": finished, "started": ago(started), "step": "gate",
            "step_started": ago(step_started), "jobs_green": 16, "jobs": 28, "run_url": "https://ci/run/1"}


def waiter(minutes: float = 20) -> dict:
    return ticket("05", enqueued=ago(minutes))


DEAD = lambda pid: False  # noqa: E731
LIVE = lambda pid: True  # noqa: E731


class Findings(unittest.TestCase):
    def kinds(self, queue, alive=DEAD, now=NOW):
        return [f["kind"] for f in qw.findings(queue, now, alive)]

    def test_a_healthy_queue_has_none(self):
        self.assertEqual(self.kinds([]), [])
        self.assertEqual(self.kinds([ticket("28", pid=7, harvest=harvest(10, 5)), waiter()], LIVE), [])
        self.assertEqual(self.kinds([ticket("28", hold={"reason": "reserved"})]), [], "nobody waits")
        self.assertEqual(self.kinds([ticket("28", hold={"reason": "reserved"}), waiter(10)]), [], "waits under 15")

    def test_idle_reservation(self):
        for head in (ticket("28", hold={"reason": "reserved"}, pid=9), ticket("28", reserved={"by": "x"}, pid=9),
                     ticket("28", pid=0)):
            with self.subTest(head=head):
                found = qw.findings([head, waiter(20)], NOW, DEAD)
                self.assertEqual([f["kind"] for f in found], ["IDLE-RESERVATION"])
                self.assertIn("IDLE-RESERVATION hal2/28: holds the front with no landing running while 1 wait "
                              "(oldest 20 min)", found[0]["line"])
                self.assertEqual(found[0]["key"], "IDLE-RESERVATION hal2/28")

    def test_dead_holder_and_a_live_pid_is_none(self):
        head = ticket("28", pid=4242, harvest=harvest(30, 10, outcome="failed", finished=ago(1)))
        self.assertEqual(self.kinds([head, waiter()]), ["DEAD-HOLDER"])
        self.assertEqual(self.kinds([head, waiter()], LIVE), [])
        self.assertIn("/mtm again", qw.findings([head, waiter()], NOW, DEAD)[0]["fix"])

    def test_stalled_gate_alone_and_not_moving_with_waiters(self):
        stalled = ticket("28", pid=7, harvest=harvest(50, 46))
        self.assertEqual(self.kinds([stalled], LIVE), ["STALLED-GATE"])
        line = qw.findings([stalled], NOW, LIVE)[0]["line"]
        self.assertEqual(line, "STALLED-GATE hal2/28: step gate for 46 min, 16/28 jobs green, https://ci/run/1")
        self.assertEqual(self.kinds([stalled, waiter()], LIVE), ["STALLED-GATE"], "50 min: not yet NOT-MOVING")
        long = ticket("28", pid=7, harvest=harvest(61, 50))
        self.assertEqual(self.kinds([long, waiter()], LIVE), ["STALLED-GATE", "NOT-MOVING"])
        self.assertEqual(self.kinds([ticket("28", pid=7, harvest=harvest(61, 5)), waiter()], LIVE), ["NOT-MOVING"])
        self.assertEqual(self.kinds([ticket("28", pid=7, harvest=harvest(61, 5))], LIVE), [], "nobody waits")

    def test_a_bad_stamp_counts_as_no_time(self):
        head = ticket("28", pid=7, harvest={**harvest(90, 90), "step_started": "garbage", "started": None})
        self.assertEqual(self.kinds([head, waiter()], LIVE), [])


class TrainBetweenRuns(unittest.TestCase):
    """Plan 0695 D43 (F9, train 56-5 after its red run end 22:19Z: 8 reds, 16 waiting): busy, never IDLE-RESERVATION."""

    TRAIN = ticket("tollman-train", hold={"reason": "reserved"}, reserved={"by": "tollman"})

    def queue(self):
        return [self.TRAIN] + [ticket(f"{n:02d}", enqueued=ago(25)) for n in range(16)]

    def test_a_train_between_its_red_run_and_its_rerun_is_busy_and_gets_no_advice(self):
        found = qw.findings(self.queue(), NOW, DEAD, between=lambda: True)
        self.assertEqual([f["kind"] for f in found], [])
        self.assertFalse(any("clear the order" in f["line"] for f in found))

    def test_the_same_reservation_with_no_train_waiting_is_still_idle(self):
        found = qw.findings(self.queue(), NOW, DEAD, between=lambda: False)
        self.assertEqual([f["kind"] for f in found], ["IDLE-RESERVATION"])
        self.assertIn("never a started landing's", found[0]["fix"])
        self.assertEqual([f["kind"] for f in qw.findings(self.queue(), NOW, DEAD)], ["IDLE-RESERVATION"])

    def test_a_field_s_reservation_is_idle_even_while_a_train_waits_and_the_check_is_lazy(self):
        asked = []
        field = [ticket("28", hold={"reason": "reserved"}), waiter(20)]
        found = qw.findings(field, NOW, DEAD, between=lambda: asked.append(1) or True)
        self.assertEqual(([f["kind"] for f in found], asked), (["IDLE-RESERVATION"], []))
        qw.findings([ticket("28", pid=7, harvest=harvest(10, 5)), waiter()], NOW, LIVE, between=lambda: asked.append(1))
        self.assertEqual(asked, [], "asked only for a tollman ticket that would be idle")

    def test_the_state_decides_by_train_state_or_open_orders(self):
        def got(doc):
            return qw.train_between_runs("/x/hal2", lambda argv, cwd: json.dumps(doc))
        self.assertEqual([got({"train": {"state": s}, "orders": []}) for s in ("red", "fixing", "retry", "landing")],
                         [True, True, True, False])
        self.assertTrue(got({"train": {"state": "landing"}, "orders": [{"id": "o1", "post": True}]}), "a fixed-wait")
        self.assertFalse(got({"train": None, "orders": []}))
        self.assertFalse(qw.train_between_runs("/x/hal2", lambda argv, cwd: "not json"))
        self.assertFalse(qw.train_between_runs("/x/hal2", mock.Mock(side_effect=OSError)))

    def test_the_duty_makes_no_wake_for_it(self):
        main = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, main, True)
        with mock.patch.object(mtm_scan, "DATA", main / "state"), \
                mock.patch.dict(os.environ, {roles.UNDER_TEST: "1", "FARMER_DIR": str(main / "state")}), \
                mock.patch.object(roles, "git", return_value=""):
            ctx = {"main": str(main), "now": NOW, "dry": True, "queue_doc": {"queue": self.queue()},
                   "train_between": lambda: True}
            self.assertEqual(qw.plan_queue({}, ctx, alive=DEAD), [])


class Duty(unittest.TestCase):
    """plan_queue over a temp state folder ($FARMER_DIR); the queue comes from the round's context."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.main = self.tmp / "hal2"
        self.main.mkdir()
        self.data = self.tmp / "state"
        for p in (mock.patch.object(mtm_scan, "DATA", self.data),
                  mock.patch.dict(os.environ, {roles.UNDER_TEST: "1", "FARMER_DIR": str(self.data)}),
                  mock.patch.object(roles, "git", return_value=""),
                  mock.patch.object(qw, "read_queue", side_effect=AssertionError("the real queue"))):
            p.start()
            self.addCleanup(p.stop)

    def tick(self, queue, now=NOW, dry=False, alive=LIVE):
        ctx = {"main": str(self.main), "now": now, "dry": dry, "queue_doc": {"queue": queue}}
        return qw.plan_queue({"name": "duty:queue"}, ctx, alive=alive, gate=None)

    def state(self) -> dict:
        return json.loads(qw.state_file(str(self.main)).read_text())

    def stalled(self):
        return [ticket("28", pid=7, harvest=harvest(50, 46))]

    def test_a_new_finding_wakes_once_and_is_kept_with_its_schema(self):
        acts = self.tick(self.stalled())
        self.assertEqual([(a["duty"], a["kind"], a["do"], a["slot"]) for a in acts],
                         [("queue", "stalled-gate", "wake", "-")])
        self.assertEqual(acts[0]["key"], f"queue:STALLED-GATE hal2/28:{qw.roletime.stamp(NOW)}")
        self.assertIn("fix the runner", acts[0]["text"])
        data = self.state()
        self.assertEqual((data["schema"], data["at"]), (1, "2026-11-02T12:00:00Z"))
        self.assertEqual(data["findings"]["STALLED-GATE hal2/28"],
                         {"kind": "STALLED-GATE", "repo": "hal2", "slot": "28", "first_seen": "2026-11-02T12:00:00Z",
                          "alarmed": None, "line": acts[0]["evidence"]["line"]})
        self.assertEqual(self.tick(self.stalled(), NOW + dt.timedelta(minutes=15)), [], "seen: no second wake")

    def test_first_seen_carries_and_past_30_min_alarms_once(self):
        self.tick(self.stalled())
        later = NOW + dt.timedelta(minutes=31)
        acts = self.tick(self.stalled(), later)
        self.assertEqual([(a["kind"], a["do"]) for a in acts], [("alarm", "run")])
        argv = acts[0]["argv"]
        self.assertEqual(argv[1:3], [str(qw.ALARM), "runner-down"])
        self.assertEqual(argv[4:], ["--repo", str(self.main), "--slot", "28"])
        self.assertIn("(for 31 min); do: look at its run", argv[3])
        kept = self.state()["findings"]["STALLED-GATE hal2/28"]
        self.assertEqual((kept["first_seen"], kept["alarmed"]), ("2026-11-02T12:00:00Z", "2026-11-02T12:31:00Z"))
        self.assertEqual(self.tick(self.stalled(), later + dt.timedelta(minutes=15)), [], "alarmed once")

    def test_the_other_findings_alarm_as_push_only_cases(self):
        idle = [ticket("28", hold={"reason": "reserved"}), waiter(20)]
        self.tick(idle, alive=DEAD)
        acts = self.tick(idle, NOW + dt.timedelta(minutes=40), alive=DEAD)
        self.assertEqual(acts[0]["argv"][2], "queue-idle-reservation")
        import alarm
        self.assertNotIn(acts[0]["argv"][2], alarm.STUCK)

    def test_a_finding_that_went_away_is_dropped_and_starts_again(self):
        self.tick(self.stalled())
        self.assertEqual(self.tick([], NOW + dt.timedelta(minutes=10)), [])
        self.assertEqual(self.state()["findings"], {})
        acts = self.tick(self.stalled(), NOW + dt.timedelta(minutes=40))
        self.assertEqual([a["do"] for a in acts], ["wake"], "new again: woken, not alarmed")

    def test_a_dry_round_writes_nothing(self):
        acts = self.tick(self.stalled(), dry=True)
        self.assertEqual([a["do"] for a in acts], ["wake"])
        self.assertFalse(qw.state_file(str(self.main)).exists())

    def test_an_unreadable_queue_plans_nothing_and_keeps_the_state(self):
        self.tick(self.stalled())
        before = self.state()
        ctx = {"main": str(self.main), "now": NOW + dt.timedelta(minutes=40), "dry": False, "queue_doc": None}
        self.assertEqual(qw.plan_queue({}, ctx, alive=LIVE, gate=None), [])
        self.assertEqual(self.state(), before)

    def test_a_broken_state_file_counts_as_empty(self):
        qw.state_file(str(self.main)).write_text("{not json")
        self.assertEqual([a["do"] for a in self.tick(self.stalled())], ["wake"])
        qw.state_file(str(self.main)).write_text(json.dumps({"schema": 9, "findings": {"x": {}}}))
        self.assertEqual(qw.load(str(self.main)), {})

    def test_the_round_s_context_carries_the_queue_it_read(self):
        import tick
        doc = {"queue": self.stalled()}
        with mock.patch.object(mtm_scan, "run_json", return_value=doc), \
                mock.patch.object(tick.deliver, "cli", return_value=(0, "[]")):
            ctx = tick.context(str(self.main), str(self.main), {}, NOW, True, paused={})
        self.assertIs(ctx["queue_doc"], doc)
        self.assertEqual([a["do"] for a in qw.plan_queue({}, ctx, alive=LIVE, gate=None)], ["wake"])

    def test_the_duty_is_wired(self):
        self.assertIn("queue", roles.FARMER.duties)
        self.assertIs(farmer.HANDLERS["duty:queue"], qw.plan_queue)
        self.assertTrue((roles.FARMER.skill / "instructions" / "queue.md").is_file())


class Cli(unittest.TestCase):
    def run_cli(self, *args, out="", err="", code=0):
        calls = []

        def runner(argv, cwd):
            calls.append((argv, cwd))
            return code, out, err

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = qw.main(["--repo-dir", "/r", *args], runner=runner, now=NOW, gate=None)
        self.assertEqual(calls, [(qw.QUEUE, "/r")])
        return rc, buf.getvalue()

    def test_healthy_findings_and_unreadable(self):
        self.assertEqual(self.run_cli(out=json.dumps({"queue": []})), (0, ""))
        doc = json.dumps({"queue": [ticket("28", hold={"reason": "reserved"}), waiter(20)]})
        rc, text = self.run_cli(out=doc)
        self.assertEqual(rc, 1)
        self.assertTrue(text.startswith("IDLE-RESERVATION hal2/28: holds the front"), text)
        rc, text = self.run_cli("--json", out=doc)
        self.assertEqual((rc, len(json.loads(text))), (1, 1))
        rc, text = self.run_cli(out="not json", err="hal2-cli-git: boom", code=1)
        self.assertEqual((rc, text), (2, "QUEUE-UNREADABLE /r: hal2-cli-git: boom\n"))
        self.assertEqual(self.run_cli("--json", out=json.dumps({"queue": []})), (0, "[]\n"))


if __name__ == "__main__":
    unittest.main()
