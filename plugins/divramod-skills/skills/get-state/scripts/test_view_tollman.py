"""The tollman's page (hal2 plan 0366 D9): the merge queue's holder, trains, ready wagons and waiters, the open land
runs and the empty state, over canned queue tickets shaped like `hal2-cli-git worktree queue --json`. No tool is called."""

import unittest
from unittest import mock

import page
import state_sources as src
import tollman_sources as ts
import view_tollman as vt

CTX = {"role": "tollman", "repo": "proj", "checkout": "tollman-proj", "top": "/x", "main": "/x"}


def ticket(slot, position, **kw) -> dict:
    base = {"position": position, "holding": False, "slot": slot, "state": "waiting", "hold": None, "waits_for": None,
            "smuggle": None, "paused_by": None, "reserved": None, "ready": None, "train": None, "rides_with": None}
    return {**base, **kw}


def run(branch, status="in_progress") -> dict:
    return {"workflow": "merge-to-main", "status": status, "branch": branch, "sha": "abc", "url": f"https://x/{branch}"}


def build(queue, runs=None, mode=None, raw=True):
    got = {"queue": queue, "mode": mode or {"mode": "production"}} if raw else None
    with mock.patch.object(ts, "raw_queue", return_value=got):
        title, sections = vt.view({"repo": "/x", "runs": runs, "mode": None}, CTX)
    assert title == "proj · tollman"
    return {s["heading"].split(" (")[0]: s for s in sections}


class Sections(unittest.TestCase):
    def test_holder_trains_ready_and_waiters(self):
        ready = {"at": "2026-10-17T03:49:56Z", "head": "569bd17a9b98ee089ea97d7d79254603753ffac5", "by": "hal2/08"}
        q = [ticket("tollman-proj", 0, holding=True, state="active",
                    train={"carrier": "tollman-proj", "cars": [{"field": "08", "branch": "08"}, {"field": "01", "branch": "01"}],
                           "at": "2026-10-18T01:00:00Z", "by": "x"}),
             ticket("08", 1, ready=ready, rides_with="tollman-proj"), ticket("05", 2), ticket("07", 3, smuggle={"x": 1})]
        got = build(q, [run("land/tollman-proj"), run("07"), run("land/08", "queued")])
        self.assertEqual(got["Mode"]["text"], "Mode: production")
        self.assertEqual(got["Holder"]["rows"], [[0, "tollman-proj", "active", ""]])
        self.assertEqual(got["Trains"]["rows"], [["tollman-proj", "tollman-proj", "08, 01", "2026-10-18T01:00:00Z"]])
        self.assertEqual(got["Ready wagons"]["rows"], [[1, "08", "2026-10-17T03:49:56Z", "569bd17a", "rides with tollman-proj"]])
        self.assertEqual(got["Waiting in order"]["rows"], [[2, "05", "waiting", ""], [3, "07", "waiting", "smuggle"]])
        self.assertEqual(got["Open land runs"]["rows"], [["tollman-proj", "merge-to-main", "in_progress", "https://x/land/tollman-proj"],
                                                          ["08", "merge-to-main", "queued", "https://x/land/08"]])

    def test_order_follows_the_position_not_the_list(self):
        got = build([ticket("b", 2), ticket("a", 1)])
        self.assertEqual([r[1] for r in got["Waiting in order"]["rows"]], ["a", "b"])

    def test_marks_of_a_held_smuggling_paused_ticket(self):
        t = ticket("12", 0, holding=True, state="held", hold={"reason": "red job"}, paused_by={"x": 1}, reserved={"by": "u"})
        self.assertEqual(vt.note(t), "held: red job; paused by a smuggle; reserved")

    def test_smuggle_mode_text(self):
        got = build([ticket("a", 0)], mode={"mode": "smuggle", "by": "user", "why": "ci down"})
        self.assertEqual(got["Mode"]["text"], "Mode: smuggle (by user, why ci down)")

    def test_empty_sections_of_a_busy_gate_have_their_lines(self):
        got = build([ticket("05", 0)], [])
        self.assertEqual(got["Holder"]["empty"], "Nobody holds the gate.")
        self.assertEqual(got["Trains"]["empty"], "No train.")
        self.assertEqual(got["Ready wagons"]["empty"], "No wagon is hitched.")
        self.assertEqual(got["Open land runs"]["empty"], "No land run is open.")


class Empty(unittest.TestCase):
    def test_nothing_queued_and_no_land_run_is_an_empty_gate(self):
        got = build([], [run("07")])
        self.assertEqual(list(got), ["Mode", "Merge queue"])
        self.assertEqual(got["Merge queue"]["empty"], "The toll gate is empty.")
        html = page.render("t", list(got.values()))
        self.assertIn("The toll gate is empty.", html)
        self.assertNotIn("<table>", html)

    def test_a_land_run_with_an_empty_queue_is_not_empty(self):
        got = build([], [run("land/07")])
        self.assertIn("Open land runs", got)
        self.assertNotIn("Merge queue", got)

    def test_no_queue_ticket_and_unknown_runs_is_no_crash(self):
        got = build([], None)
        self.assertIn("Open land runs", got)
        self.assertNotIn("Merge queue", got)  # not "empty" while the land runs are unknown
        self.assertIn("unknown", got["Open land runs"]["empty"])

    def test_unknown_queue_and_runs_say_so(self):
        got = build(None, None, raw=False)
        self.assertIn("unknown", got["Merge queue"]["empty"])
        self.assertIn("unknown", got["Open land runs"]["empty"])
        self.assertEqual(got["Mode"]["text"], "Mode unknown.")


class Source(unittest.TestCase):
    def test_the_raw_queue_keeps_tickets_and_mode(self):
        raw = {"queue": [{"slot": "01"}, "junk"], "mode": {"mode": "production"}, "expired": []}
        with mock.patch.object(src, "tool_json", return_value=raw) as tool:
            got = ts.raw_queue("/m")
        self.assertEqual(got, {"queue": [{"slot": "01"}], "mode": {"mode": "production"}})
        self.assertEqual(tool.call_args.args[0], ["hal2-cli-git", "worktree", "queue", "--json"])

    def test_a_tool_that_gives_nothing_or_junk_is_unknown(self):
        for value in (None, [], {"queue": "x"}):
            with mock.patch.object(src, "tool_json", return_value=value):
                self.assertIsNone(ts.raw_queue("/m"))


if __name__ == "__main__":
    unittest.main()
