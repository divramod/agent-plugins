"""Hal2 plan 0294 step 15 (D29): the orphan rule leaves a field in an open transplant of plan 0286 alone."""

import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401
import boss
import mtm_scan
import tick
import transplant_mark

NOW = dt.datetime(2026, 10, 13, 10, 0)  # local, like the round's clock


def stamp(minutes_ago: int) -> str:
    return (NOW.astimezone() - dt.timedelta(minutes=minutes_ago)).astimezone(dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z")


def record(src="34", dst="09", state="prepared", ago=5, **kw):
    return {"id": f"x-{src}-to-{dst}", "from": src, "to": dst, "state": state, "prepared": stamp(ago), **kw}


class Orphan(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "09").mkdir()
        (self.tmp / "09" / "HANDOFF.md").write_text("x")
        self.finding = {"kind": "work-without-agent", "slot": "09", "why": "no agent"}
        self.wt = {"slot": "09", "path": str(self.tmp / "09"), "ahead": 1, "plan": "0286-x", "agent_state": None,
                   "pane": None}

    def planned(self, transplants=(), wt=None):
        snap = {"findings": [self.finding], "queue": [], "worktrees": [wt or self.wt], "landings": []}
        return boss.plan(snap, {"now": NOW, "log": [], "main": "/x/hal2", "transplants": list(transplants),
                          "panes": {"farmer-hal2": "%fa"}})

    def test_without_a_mark_the_rule_acts_as_before(self):
        a = self.planned()
        self.assertEqual([(x["do"], x["kind"]) for x in a], [("run", "orphan")])
        self.assertEqual(a[0]["text"], "started a session in 09 with /handoff c")
        self.assertEqual([x["do"] for x in self.planned([record("34", "11")])], ["run"], "another pair's transplant")
        self.assertEqual([x["do"] for x in self.planned([record(state="arrived", ago=5)])], ["run"], "over")
        self.assertEqual([x["do"] for x in self.planned([record(state="cancelled")])], ["run"], "over")

    def test_the_target_of_an_open_transplant_is_skipped(self):
        for state in ("prepared", "driven"):
            self.assertEqual(self.planned([record(state=state, driven=stamp(2))]), [], state)

    def test_the_source_of_an_open_transplant_is_skipped_also_without_a_handoff(self):
        self.assertEqual(self.planned([record("09", "11", "driven", driven=stamp(1))]), [])
        (self.tmp / "09" / "HANDOFF.md").unlink()
        self.assertEqual(self.planned([record("09", "11")]), [], "no wake either")
        self.assertEqual([x["do"] for x in self.planned()], ["wake"])

    def test_an_old_prepared_transplant_skips_both_fields_and_is_reported_once(self):
        old = record(ago=61)
        for field in ("09", "34"):  # the target and the source
            self.finding["slot"] = field
            a = self.planned([old], dict(self.wt, slot=field))
            self.assertEqual([(x["do"], x["kind"], x["slot"]) for x in a],
                             [("send", "transplant-stale", "farmer-hal2")], field)
            self.assertNotIn("/handoff c", a[0]["text"].replace("`/transplant cancel 34`", ""))
        self.assertEqual(a[0]["key"], f"transplant-stale:34:09:{old['prepared']}")
        self.assertEqual(a[0]["pane"], "%fa")
        self.assertIn("transplant 34 to 09 is prepared for 61 minutes", a[0]["text"])
        self.assertIn("`hal2-cli-git worktree transplant 34 09` again", a[0]["text"])
        self.assertIn("`/transplant cancel 34`", a[0]["text"])
        (self.tmp / "09" / "HANDOFF.md").unlink()
        self.assertEqual([x["do"] for x in self.planned([record(ago=120)])], ["send"], "no wake either")

    def test_both_fields_of_one_old_transplant_give_one_report_and_a_second_round_none(self):
        old = record(ago=90)
        other = {"kind": "work-without-agent", "slot": "34", "why": "no agent"}
        snap = {"findings": [self.finding, other], "queue": [], "landings": [],
                "worktrees": [self.wt, dict(self.wt, slot="34", path=str(self.tmp / "34"))]}
        ctx = {"now": NOW, "log": [], "main": "/x/hal2", "transplants": [old], "panes": {}}
        planned = boss.plan(snap, ctx)
        self.assertEqual([x["kind"] for x in planned], ["transplant-stale"])
        sent = [{"at": NOW.isoformat(), "key": planned[0]["key"], "kind": "transplant-stale"}]
        later = NOW + dt.timedelta(minutes=30)
        self.assertEqual(tick.fresh(boss.plan(snap, {**ctx, "now": later}), sent, later), [], "once, not every round")

    def test_an_old_driven_source_never_gets_a_session(self):
        self.finding["slot"] = "34"
        wt = dict(self.wt, slot="34")
        for ago in (5, 300):
            a = self.planned([record(state="driven", ago=600, driven=stamp(ago))], wt)
            self.assertNotIn("run", [x["do"] for x in a])
            self.assertNotIn("wake", [x["do"] for x in a])
        self.assertEqual([x["kind"] for x in a], ["transplant-stale"])

    def test_a_fresh_mark_reports_nothing(self):
        self.assertEqual(self.planned([record(ago=59)]), [])

    def test_a_driven_record_is_fresh_from_its_driven_time(self):
        self.assertEqual(self.planned([record(state="driven", ago=300, driven=stamp(10))]), [])

    def test_the_marker_in_the_target_counts_when_no_record_is_read(self):
        marker = self.tmp / "09" / "plans" / "CURRENT_PLAN"
        marker.parent.mkdir()
        marker.write_text("transplant-from-34\n")
        self.assertEqual(self.planned(), [])
        old = NOW.astimezone().timestamp() - 3 * 3600
        os.utime(marker, (old, old))
        self.assertEqual(self.planned(), [], "the marker has no age: protected, nothing reported")
        marker.write_text("0286-transplant-command\n")
        self.assertEqual(self.planned()[0]["text"], "started a session in 09 with /handoff c")

    def test_a_record_without_a_readable_time_is_old_and_reported(self):
        self.assertEqual([x["kind"] for x in self.planned([{"from": "34", "to": "09", "state": "prepared"}])],
                         ["transplant-stale"])


class History(unittest.TestCase):
    def test_the_command_s_json_is_read_tolerantly(self):
        good = {"transplants": [record(), "junk", {"future": 1}], "status": "ok"}
        self.assertEqual(len(transplant_mark.history("/x", lambda a, c: good)), 2)
        self.assertEqual(transplant_mark.history("/x", lambda a, c: None), [], "no command, no answer")
        self.assertEqual(transplant_mark.history("/x", lambda a, c: {"transplants": "x"}), [])
        self.assertEqual(transplant_mark.history("/x", lambda a, c: ["x"]), [])

    def test_the_handler_reads_the_records_only_when_an_orphan_is_found(self):
        ctx = {"now": NOW, "log": [], "main": "/x/hal2", "top": "/x/wm", "dry": True}
        quiet = {"findings": [], "queue": [], "worktrees": [], "landings": []}
        with mock.patch.object(mtm_scan, "snapshot", return_value=quiet), \
                mock.patch.object(transplant_mark, "history", return_value=[]) as read:
            boss.handler({}, ctx)
            read.assert_not_called()
        orphan = {**quiet, "findings": [{"kind": "work-without-agent", "slot": "09", "why": "x"}],
                  "worktrees": [{"slot": "09", "path": "/nowhere", "agent_state": None, "plan": ""}]}
        with mock.patch.object(mtm_scan, "snapshot", return_value=orphan), \
                mock.patch.object(transplant_mark, "history", return_value=[record()]) as read:
            self.assertEqual(boss.handler({}, ctx), [])
            read.assert_called_once_with("/x/hal2")


if __name__ == "__main__":
    unittest.main()
