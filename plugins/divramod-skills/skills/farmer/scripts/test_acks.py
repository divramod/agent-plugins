"""Hal2 plan 0137 (the user's point 5): every farmer instruction carries an id and asks for an ack."""

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import acks
import mtm_scan
import tick

NOW = dt.datetime(2026, 10, 5, 8, 0)


def at(minutes):
    return (NOW - dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")


def asked(minutes, ack_id="12-1", slot="12"):
    return {"at": at(minutes), **acks.ask_entry(slot, ack_id, acks.stamp("farmer: go on", ack_id), "t:12", "tick")}


def plan(log):
    return [(a["do"], a["kind"], a["slot"]) for a in acks.plan(log, NOW, {"12": "t:12"}, lambda pane: "screen")]


class Stamp(unittest.TestCase):
    def test_the_id_goes_on_the_first_line_and_the_reply_on_the_last(self):
        self.assertEqual(acks.stamp("farmer (development lead): run /handoff", "12-3"),
                         "farmer [12-3] (development lead): run /handoff\n" + acks.REPLY.format(id="12-3"))
        self.assertTrue(acks.stamp("Your last turn failed.", "04-1").startswith("farmer [04-1]: Your last turn"))
        self.assertTrue(acks.stamp('farmer: the user decided: "go"', "12-2").startswith(
            'farmer [12-2]: the user decided: "go"'))
        self.assertEqual(acks.stamped_id(acks.stamp("x", "07-9")), "07-9")

    def test_ids_count_per_slot(self):
        log = [asked(1, "12-1"), asked(1, "04-1", "04")]
        self.assertEqual((acks.next_id(log, "12"), acks.next_id(log, "05")), ("12-2", "05-1"))


class FollowUp(unittest.TestCase):
    def test_no_ack_resends_once_then_wakes(self):
        self.assertEqual(plan([asked(5)]), [])
        self.assertEqual(plan([asked(11)]), [("send", "resend", "12")])
        resent = [asked(25), {"at": at(14), "kind": "resend", "slot": "12", "key": "ack-resend:12-1"}]
        self.assertEqual(plan(resent[:1] + [dict(resent[1], at=at(5))]), [])
        self.assertEqual(plan(resent), [("wake", "no-ack", "12")])
        self.assertEqual(acks.plan(resent, NOW, {}, lambda pane: "the screen")[0]["evidence"]["screen"], "the screen")

    def test_started_stops_the_clock_done_closes_refused_wakes(self):
        ack = lambda status, why="": {"at": at(1), "kind": "ack", "slot": "12", "what": status, "note": why,
                                      "id": "12-1"}
        self.assertEqual(plan([asked(30), ack("started")]), [])
        self.assertEqual(plan([asked(30), ack("done")]), [])
        self.assertEqual(plan([asked(30), ack("refused", "a paid step")]), [("wake", "refused", "12")])

    def test_a_resend_keeps_its_id_and_is_done_once(self):
        a = acks.plan([asked(11)], NOW, {}, lambda pane: "")[0]
        self.assertEqual((a["ack_id"], a["pane"]), ("12-1", "t:12"))
        self.assertEqual(tick.fresh([a], [{"at": at(1), "key": "ack-resend:12-1"}], NOW), [])


class Stale(unittest.TestCase):
    """L74 of the tollman (2026-10-21): acks of week-old messages (20-1, 27-1, 28-1, sent 2026-10-14 as wagon-master)
    woke the session as new no-ack and refused items once their keys' week had run out."""

    def test_a_week_old_instruction_refused_or_unanswered_never_wakes(self):
        week = 7 * 24 * 60
        refused = {"at": at(week - 5), "kind": "ack", "slot": "12", "what": "refused", "note": "x", "id": "12-1"}
        self.assertEqual(plan([asked(week), refused]), [])
        self.assertEqual(plan([asked(week)]), [("record", "ack-void", "12")],
                         "no ack, a week old: closed void (plan 0530 D6), no re-send, no wake")
        fresh = dict(refused, at=at(30))
        self.assertEqual(plan([asked(week), fresh]), [("wake", "refused", "12")], "a refusal of today still wakes")

    def test_an_instruction_sent_under_a_retired_role_name_never_wakes(self):
        old = {"at": at(30), **acks.ask_entry("20", "20-1", acks.stamp("wagon-master: fix it", "20-1", "wagon-master"),
                                              "t:20", "tick")}
        self.assertEqual(plan([old]), [])
        self.assertEqual(plan([dict(old, text=acks.stamp("fix it", "20-1", "tollman"))]), [("send", "resend", "20")])


def rows(kind):
    return [{"pane_id": "%7", "slot": "07", "project": "/y", "kind": kind}]


CLAUDE = rows("claude")


class ReplyByKind(unittest.TestCase):
    def line(self, kind, role="farmer"):
        a = tick.act("lead", "x", "send", "07", pane="%7", text="go")
        with tempfile.TemporaryDirectory() as d:
            old, mtm_scan.DATA = mtm_scan.DATA, Path(d)
            try:
                acks.stamp_send(a, "/y", role, rows(kind) if kind else [])
            finally:
                mtm_scan.DATA = old
        return a["text"].splitlines()[-1]

    def test_claude_gets_send_message_every_other_kind_the_shell_ack(self):
        self.assertIn("by SendMessage to the farmer session", self.line("claude"))
        for kind in ("codex", "opencode", "grok", "antigravity", None):
            last = self.line(kind)
            self.assertIn(f"python3 {Path(acks.__file__).resolve().parent}/acks.py ack 07-1 started|done|refused", last)
            self.assertIn("--role farmer --repo /y", last, kind)
            self.assertNotIn("SendMessage", last)

    def test_a_resend_to_a_grok_pane_carries_the_shell_line(self):
        first = acks.stamp("farmer: go", "07-1")  # first sent to a Claude pane
        a = acks.plan([{"at": at(11), **acks.ask_entry("07", "07-1", first, "%7", "tick")}], NOW, {}, lambda p: "")[0]
        self.assertIn("SendMessage", a["text"])
        acks.stamp_send(a, "/y", "farmer", rows("grok"))
        self.assertEqual((a["ack_id"], a["text"].count("\n")), ("07-1", 1))
        self.assertIn("acks.py ack 07-1", a["text"].splitlines()[-1])
        self.assertTrue(a["text"].startswith("farmer [07-1]: go"))

    def test_the_tollman_order_to_a_codex_pane_names_its_role(self):
        self.assertIn("--role tollman --repo /y", self.line("codex", "tollman"))

    def test_the_shell_ack_lands_in_the_scratch_log_from_another_cwd(self):
        import os
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as elsewhere:
            repo = Path(d) / "hal2"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            env = {**os.environ, "FARMER_DIR": d, "HAL2_HOME": d}
            r = subprocess.run([sys.executable, acks.__file__, "ack", "07-1", "done", "fixed", "abc", "--role",
                                "tollman", "--repo", str(repo)], cwd=elsewhere, env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            logs = list(Path(d).rglob("log.jsonl"))
            self.assertEqual(len(logs), 1, logs)
            self.assertIn('"kind": "ack"', logs[0].read_text())
            self.assertIn("tollman", str(logs[0]))


class TickStamps(unittest.TestCase):
    def test_a_send_is_stamped_and_logged_before_it_is_typed(self):
        with tempfile.TemporaryDirectory() as d:
            old, mtm_scan.DATA = mtm_scan.DATA, Path(d)
            try:
                main = str(Path(d) / "hal2")
                a = tick.act("lead", "no-plan", "send", "07", pane="%7", text="farmer (development lead): fill it")
                acks.stamp_send(a, main, agents=CLAUDE)
                acks.stamp_send(a, main, agents=CLAUDE)  # a second call (a re-send) keeps the id
                log = mtm_scan.entries(mtm_scan.state_dir(main) / "log.jsonl")
                self.assertEqual([(e["kind"], e["id"], e["slot"]) for e in log], [("ask-ack", "07-1", "07")])
                self.assertTrue(a["text"].startswith("farmer [07-1] (development lead): fill it\nReply `ack 07-1:"))
                self.assertEqual(acks.instructions(log)["07-1"]["text"], a["text"])
            finally:
                mtm_scan.DATA = old


if __name__ == "__main__":
    unittest.main()
