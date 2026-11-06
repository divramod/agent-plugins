import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import autopilot_duty as ad
import duties
import tick

NOW = dt.datetime(2026, 11, 5, 12, 0, tzinfo=dt.timezone.utc)
CTX = {"top": "/x/farmer", "main": "/x/hal2", "now": NOW, "log": [], "panes": {}}


def rec(minutes_ago, action="freeze", field="01", **kw):
    at = (NOW - dt.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"schema": 1, "at": at, "repo": "hal2", "field": field, "action": action, "why": "w", "trigger": "gate",
            "outcome": "done", "error": None, "by": "daemon", **kw}


def view(age=30, mode="work", records=()):
    return {"age": age, "interval_s": 60, "mode": mode, "records": list(records)}


def report(*changes, tell=None):
    return {"schema": 1, "repo": "hal2", "mode": "work", "changes": list(changes), "tell_tollman": tell}


FREEZE = {"field": "01", "action": "freeze", "why": "w", "argv": []}
START = {"field": "07", "action": "start", "why": "top", "argv": ["hal2-cli-git", "worktree", "run", "07"]}


def plan(rep, v, log=()):
    return duties.plan_autopilot({}, {**CTX, "log": list(log)}, report=rep, orders=[], view=v)


def kinds(acts):
    return [(a["do"], a["kind"]) for a in tick.fresh(acts, [], NOW)]


class Heartbeat(unittest.TestCase):
    def test_a_fresh_heartbeat_does_not_tick_or_start(self):
        self.assertEqual(plan(report(FREEZE, START), view(age=170)), [])

    def test_a_stale_or_missing_heartbeat_ticks_and_starts(self):
        for age in (181, None):
            self.assertEqual(kinds(plan(report(FREEZE, START), view(age=age))),
                             [("run", "limit"), ("run", "start")])

    def test_a_fresh_heartbeat_still_relays_the_trains_tell(self):
        tell = {"key": "autopilot:train:11", "text": "bring them in"}
        self.assertEqual(kinds(plan(report(FREEZE, tell=tell), view(age=10))), [("send", "train")])

    def test_the_limit_is_three_intervals_of_the_farms_store(self):
        v = {**view(age=500), "interval_s": 200}
        self.assertTrue(ad.alive(v))
        self.assertFalse(ad.alive({**v, "age": 601}))

    def test_a_busy_tick_means_the_daemon_ticks(self):
        busy = mock.Mock(returncode=1, stdout="", stderr="Error: another autopilot tick of hal2 runs")
        with mock.patch("bounded.run", return_value=busy):
            self.assertEqual(ad.tick(["--repo-dir", "/x"]), 0)
        red = mock.Mock(returncode=1, stdout="", stderr="boom")
        with mock.patch("bounded.run", return_value=red):
            self.assertEqual(ad.tick(["--repo-dir", "/x"]), 1)

    def test_the_heartbeat_file_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ad.HEARTBEAT).write_text(json.dumps(
                {"schema": 1, "at": "2026-11-05T11:59:00Z", "farms": {"hal2": {"mode": "ci"}}}))
            v = ad.view_of("/x/hal2", NOW, folder=Path(d))
        self.assertEqual((v["age"], v["mode"]), (60.0, "ci"))
        self.assertIsNone(ad.view_of("/x/hal2", NOW, folder=Path("/nonexistent/x"))["age"])


class Journal(unittest.TestCase):
    def test_records_are_copied_once(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ad.JOURNAL).write_text("\n".join(json.dumps(r) for r in (
                rec(10), rec(5, "thaw"), {**rec(4), "repo": "other"}, {**rec(3), "schema": 2})) + "\nnot json\n")
            written = []
            with mock.patch("autopilot_duty.read_log", side_effect=lambda m: list(written)):
                self.assertEqual(ad.copy("/x/hal2", lambda m, e: written.append(e), NOW, Path(d)), 2)
                self.assertEqual(ad.copy("/x/hal2", lambda m, e: written.append(e), NOW, Path(d)), 0)
        self.assertEqual([w["kind"] for w in written], ["journal-freeze", "journal-thaw"])
        self.assertEqual(written[0]["slot"], "01")
        self.assertTrue(written[0]["key"].startswith("journal:"))

    def test_new_records_plan_one_copy_run_and_none_once_logged(self):
        v = view(records=[rec(10)])
        self.assertEqual(kinds(plan(report(), v)), [("run", "journal")])
        logged = [{**ad.log_entry(rec(10)), "at": NOW.isoformat()}]
        self.assertEqual(plan(report(), v, logged), [])

    def test_old_records_are_not_copied(self):
        self.assertEqual(ad.new_records(view(records=[rec(60 * 24 * 4)]), [], NOW), [])


class StuckFreeze(unittest.TestCase):
    def acts(self, v, log=()):
        return tick.fresh(plan(report(), v, log), list(log), NOW)

    def test_a_freeze_over_90_min_without_a_mac_job_wakes_and_pushes_once(self):
        v = view(mode="work", records=[rec(100)])
        acts = [a for a in self.acts(v) if a["kind"] != "journal"]
        self.assertEqual([(a["do"], a["kind"]) for a in acts], [("wake", "freeze-stuck"), ("run", "freeze-alarm")])
        self.assertIn("alarm.py", acts[1]["argv"][1])
        self.assertEqual(acts[1]["argv"][2], "autopilot-freeze")
        log = [{"at": NOW.isoformat(), "key": a["key"]} for a in acts]
        self.assertEqual([a for a in self.acts(v, log) if a["kind"] != "journal"], [], "once")

    def test_no_alarm_with_a_mac_job_a_thaw_or_a_young_freeze(self):
        for v in (view(mode="ci", records=[rec(100)]), view(records=[rec(100), rec(50, "thaw")]),
                  view(records=[rec(60)])):
            self.assertEqual([a for a in self.acts(v) if a["kind"] != "journal"], [])



class Check(unittest.TestCase):
    def test_due_check_lists_the_autopilot_and_runners_duties(self):
        import contextlib
        import io
        import subprocess
        import due
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            role = Path(d) / "roles/farmer/ROLE.md"
            role.parent.mkdir(parents=True)
            role.write_text('---\nduties:\n  autopilot: "*/15 * * * *"\n  runners: "*/15 * * * *"\n'
                            'servant_limit: auto\nnotify: every-round\n---\n')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(due.main(["check", "--repo", d]), 0)
        self.assertIn("- duty autopilot: */15 * * * *", out.getvalue())
        self.assertIn("- duty runners: */15 * * * *", out.getvalue())


if __name__ == "__main__":
    unittest.main()
