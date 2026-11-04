"""Hal2 plan 0514 step 6 (D17): no silent duty. A farmer or tollman duty that fails, times out or is deferred past its
next run is reported on the role's message board (and a disk or production duty through the notifier), and each
duty's last good run is counted in duty-health.json. No real session, timer or notification: the notifier is a fake."""

import contextlib
import dataclasses
import datetime as dt
import fcntl
import io
import json
import subprocess
import unittest
from unittest import mock

import board
import duty_health
import due
import mtm_scan
import role_cli
import roles
import tick
from test_farmer import NOW, Repo
from test_wiring import SNAP, WAGON, WagonRepo

CRON = '"*/15 * * * *"'
ROLE = f"---\nduties:\n  lead: {CRON}\n  ci: {CRON}\n  prs: {CRON}\n  sync: {CRON}\nnotify: every-round\n---\n\n# x\n"
TIMED_OUT = "Command '['gh', 'run', 'list']' timed out after 900 seconds"


def lead_crashes(item, ctx):
    raise RuntimeError("scan blew up")


def ci_times_out(item, ctx):
    return [tick.act("ci", "scan", "run", "-", argv=["slow-scan"], text="scan")]


def prs_deferred(item, ctx):
    return [tick.act("prs", "close", "record", "-", text="closing put off", health="deferred",
                     why="a train builds: the PR close waits")]


def quiet(item, ctx):
    return []


class Quiet:
    """A round without a real session, git network call or summary."""

    def patch(self, now_sh=None):
        def sh(argv, cwd, timeout=900):
            if argv[0] == "slow-scan":
                return 127, TIMED_OUT
            return (0, json.dumps({"status": "ok"})) if argv[0] == "hal2-cli-git" else real(argv, cwd, timeout)

        real = tick.sh
        for p in (mock.patch.object(tick, "sh", sh), mock.patch.object(tick, "summarize"),
                  mock.patch.object(mtm_scan, "snapshot", return_value=SNAP)):
            p.start()
            self.addCleanup(p.stop)


class FarmerRound(Quiet, Repo):
    def setUp(self):
        super().setUp()
        (self.slot / tick.ROLE).write_text(ROLE)
        self.patch()
        self.handlers = {"duty:lead": lead_crashes, "duty:ci": ci_times_out, "duty:prs": prs_deferred,
                         "duty:sync": quiet}

    def notes(self):
        return [r["text"] for r in board.lines(str(self.main), "note", role="farmer")]

    def health(self):
        return json.loads((self.data / "hal2" / "duty-health.json").read_text())

    def test_a_failed_a_timed_out_and_a_deferred_duty_are_reported_and_the_round_goes_on(self):
        r = tick.run(str(self.slot), False, self.handlers, NOW)
        self.assertEqual([(x["duty"], x["status"]) for x in r["duty_reports"]],
                         [("duty:lead", "failed"), ("duty:ci", "timeout"), ("duty:prs", "deferred")])
        notes = self.notes()
        self.assertEqual(len(notes), 3)
        self.assertIn("duty:lead failed: RuntimeError: scan blew up", notes[0])
        self.assertIn("duty:ci timeout: scan: exit 127", notes[1])
        self.assertIn("duty:prs deferred: a train builds", notes[2])
        self.assertTrue(all("no good run yet" in n for n in notes))
        self.assertEqual(set(due.last_runs(str(self.slot))), {"duty:lead", "duty:ci", "duty:prs", "duty:sync"},
                         "a failed duty is still recorded as run: it is retried at its next cron, not every tick")
        h = self.health()
        self.assertEqual(h["schema"], 1)
        self.assertEqual(h["duties"]["duty:sync"]["good"], 1, "the quiet duty's good run is counted")
        self.assertEqual(h["duties"]["duty:sync"]["last_good"], board.utc(NOW))
        self.assertEqual(h["duties"]["duty:lead"]["bad"], 1)
        self.assertEqual(r["wake"], [], "a report costs no model wake")

    def test_a_dry_round_reports_and_writes_nothing(self):
        r = tick.run(str(self.slot), True, self.handlers, NOW)
        self.assertNotIn("duty_reports", r)
        self.assertFalse((self.data / "hal2" / "duty-health.json").exists())
        self.assertEqual(self.notes(), [])

    def test_the_same_failure_is_said_once_then_after_six_hours_and_a_good_run_clears_it(self):
        tick.run(str(self.slot), False, self.handlers, NOW)
        later = NOW + dt.timedelta(minutes=30)
        self.handlers["duty:lead"] = quiet
        r = tick.run(str(self.slot), False, self.handlers, later)
        self.assertEqual(r["duty_reports"], [], "ci and prs still bad, but already said")
        self.assertEqual(len(self.notes()), 3)
        lead = self.health()["duties"]["duty:lead"]
        self.assertEqual((lead["good"], lead["bad"], lead["status"]), (1, 0, "ok"))
        self.assertNotIn("reported", lead)
        r = tick.run(str(self.slot), False, self.handlers, NOW + duty_health.REPEAT + dt.timedelta(minutes=30))
        self.assertEqual([x["duty"] for x in r["duty_reports"]], ["duty:ci", "duty:prs"])
        self.assertEqual(len(self.notes()), 5)

    def test_a_busy_tick_reports_the_duties_that_missed_their_run_once_every_five_minutes(self):
        wiring = roles.FARMER
        for name in ("duty:lead", "duty:prs", "duty:sync"):
            due.record_run(str(self.slot), name, NOW - dt.timedelta(hours=3))
        due.record_run(str(self.slot), "duty:ci", NOW - dt.timedelta(minutes=5))
        sent = []
        reports = duty_health.busy(str(self.slot), wiring, NOW, notifier=lambda *a: sent.append(a))
        self.assertEqual({r["duty"] for r in reports}, {"duty:lead", "duty:prs", "duty:sync"})
        self.assertTrue(all(r["status"] == "deferred" for r in reports))
        self.assertEqual(sent, [], "the farmer has no disk or production duty")
        self.assertEqual(len(self.notes()), 3)
        self.assertEqual(duty_health.busy(str(self.slot), wiring, NOW + dt.timedelta(minutes=2)), [])
        self.assertEqual(len(self.notes()), 3)

    def test_the_tick_that_finds_the_lock_held_looks_for_deferred_duties(self):
        due.record_run(str(self.slot), "duty:lead", dt.datetime.now() - dt.timedelta(hours=3))
        out = io.StringIO()
        with role_cli.state(str(self.slot), roles.FARMER).joinpath("tick.lock").open("w") as lock, \
                mock.patch.object(role_cli, "missing", return_value=[]), \
                mock.patch.object(role_cli, "mode", return_value="timer"), contextlib.redirect_stdout(out):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code = role_cli.run_tick(str(self.slot), False, False, {}, roles.FARMER)
        self.assertEqual((code, out.getvalue().strip()), (0, "busy: another tick runs"))
        self.assertTrue(any("duty:lead deferred" in n for n in self.notes()))


class Overdue(unittest.TestCase):
    def test_a_duty_is_late_when_its_next_run_is_half_an_hour_past_and_a_weekly_one_is_not_late_for_a_week(self):
        schedule = {"duty:a": "*/15 * * * *", "duty:b": "*/15 * * * *", "duty:c": "0 9 * * 1", "duty:new": "* * * * *"}
        now = dt.datetime(2026, 10, 3, 10, 20)  # a Saturday
        last = {"duty:a": dt.datetime(2026, 10, 3, 10, 15), "duty:b": dt.datetime(2026, 10, 3, 9, 0),
                "duty:c": dt.datetime(2026, 9, 28, 9, 0)}
        late = duty_health.overdue(schedule, last, now)
        self.assertEqual([n for n, _ in late], ["duty:b"])
        self.assertEqual(late[0][1], "due since 2026-10-03 09:15, not run for 65 min")
        monday = dt.datetime(2026, 10, 5, 9, 31)
        self.assertEqual([n for n, _ in duty_health.overdue({"duty:c": "0 9 * * 1"}, last, monday)], ["duty:c"])

    def test_status_of_reads_the_executed_actions(self):
        ok = tick.act("d", "k", "run", argv=["x"]) | {"exit": 0}
        offline = tick.act("d", "k", "run", argv=["x"]) | {"exit": tick.OFFLINE}
        bad = tick.act("d", "k", "run", argv=["x"]) | {"exit": 2, "output": "boom\nlast line"}
        self.assertEqual(duty_health.status_of([ok, offline]), ("ok", ""))
        self.assertEqual(duty_health.status_of([ok, bad]), ("failed", "k: exit 2 last line"))
        self.assertEqual(duty_health.status_of([tick.act("d", "k", "wake", text="t")]), ("ok", ""))
        err = duty_health.crashed("d", subprocess.TimeoutExpired("git", 5))
        self.assertEqual(duty_health.status_of(err)[0], "timeout")


class TollmanRound(Quiet, WagonRepo):
    """The tollman's duties: a disk or production duty also goes to the notifier, another one only to the board."""

    def setUp(self):
        super().setUp()
        self.wiring = dataclasses.replace(WAGON, duties=("trains", "prune", "yard"))
        (self.wm / self.wiring.role_file).write_text(ROLE.replace("lead:", "trains:").replace("ci:", "prune:")
                                                     .replace("prs:", "yard:").replace("  sync: " + CRON + "\n", ""))
        self.patch()
        self.sent = []
        self.handlers = {"duty:trains": lead_crashes, "duty:prune": ci_times_out, "duty:yard": prs_deferred}

    def test_a_production_and_a_disk_duty_are_notified_and_the_yard_only_noted(self):
        with mock.patch.object(duty_health, "lookout_notifier", lambda *a: self.sent.append(a) or []), \
                mock.patch.dict("os.environ", {roles.UNDER_TEST: ""}):
            r = tick.run(str(self.wm), False, self.handlers, NOW, wiring=self.wiring)
        self.assertEqual([(x["duty"], x["status"]) for x in r["duty_reports"]],
                         [("duty:trains", "failed"), ("duty:prune", "timeout"), ("duty:yard", "deferred")])
        notes = board.lines(str(self.main), "note", role="tollman")
        self.assertEqual([n["to"] for n in notes], ["farmer-hal2"] * 3)
        self.assertEqual([n["from"] for n in notes], ["tollman-hal2"] * 3)
        self.assertEqual([(s[0], s[3]) for s in self.sent],
                         [("tollman: trains failed", "duty:trains"), ("tollman: prune timeout", "duty:prune")])
        self.assertIn("scan blew up", self.sent[0][1])
        health = json.loads((self.data / "hal2" / "tollman" / "duty-health.json").read_text())
        self.assertEqual(set(health["duties"]), {"duty:trains", "duty:prune", "duty:yard"})
        self.assertFalse((self.data / "hal2" / "duty-health.json").exists(), "nothing of the farmer's is written")

    def test_a_notifier_that_fails_never_stops_the_round(self):
        def boom(*a):
            raise OSError("no tool")

        with mock.patch.object(duty_health, "lookout_notifier", boom), mock.patch.dict("os.environ", {roles.UNDER_TEST: ""}):
            r = tick.run(str(self.wm), False, self.handlers, NOW, wiring=self.wiring)
        self.assertEqual(len(r["duty_reports"]), 3)
        self.assertEqual(len(board.lines(str(self.main), "note", role="tollman")), 3)


if __name__ == "__main__":
    unittest.main()
