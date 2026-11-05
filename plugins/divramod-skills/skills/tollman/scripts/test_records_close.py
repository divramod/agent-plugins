"""Hal2 plan 0611 step 4 (design.md §2, D4, D8): a tollman record closes only when its closer (records_close.py) sees
its code fact, and stays open otherwise: one case per kind, and no close by age or by a word. A scratch state
folder, no real sleep; the facts that come from other programs (the queue, the cars, the agents list) are given."""

import argparse
import contextlib
import datetime as dt
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import foreman_wake
import mtm_scan
import records_close
import records_kinds
import role_records
import tollman
import train_state

T0 = dt.datetime(2026, 11, 4, 10, 0, 0, tzinfo=dt.timezone.utc)
MAIN = "/repo"


def at(seconds: int) -> dt.datetime:
    return T0 + dt.timedelta(seconds=seconds)


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)]))
        patch = mock.patch.object(mtm_scan, "state_dir", lambda main, role="farmer": self.tmp / role)
        patch.start()
        self.addCleanup(patch.stop)
        (self.tmp / "tollman").mkdir()
        (self.tmp / "farmer").mkdir()

    def line(self, kind, slot, seconds, **keys):
        train_state.append(MAIN, kind, slot, at(seconds), **keys)

    def add(self, type, slot, seconds=0, **keys):
        return records_kinds.add(MAIN, type, slot, f"{type} for {slot}", event=None, now=at(seconds), **keys)["id"]

    def sweep(self, seconds=100, **facts):
        return role_records.sweep(MAIN, records_kinds.ROLE, at(seconds), dict(facts))

    def state(self, rid):
        return role_records.fold(role_records.lines(MAIN, records_kinds.ROLE))[rid]

    def assertOpen(self, rid, **facts):
        out = self.sweep(**facts)
        self.assertFalse(self.state(rid)["closed"], out)
        self.assertEqual([x for x in out if x.startswith(rid + " ")], [])

    def assertClosed(self, rid, how, has, **facts):
        out = self.sweep(**facts)
        rec = self.state(rid)
        self.assertTrue(rec["closed"], out)
        self.assertEqual((rec["how"], rec["closed_by"]), (how, "code"))
        self.assertIn(has, rec["evidence"])
        self.assertEqual([x for x in out if x.startswith(rid + " ")], [f"{rid} closed by {how}: {rec['evidence']}"])


class FixOrder(Store):
    def test_open_until_its_fixed_line_and_then_its_train_landed(self):
        self.line("order", "tollman", 1, train="A", field="07", id="07-fix-1", branch="07-train-fix")
        rid = self.add("fix-order", "07", 2, order="07-fix-1", train="A")
        self.assertOpen(rid)
        self.line("fixed", "tollman", 3, train="A", field="07", id="07-fix-1", sha="abc123", commit="m1")
        self.assertOpen(rid)  # merged, not landed: the run is not green yet
        self.line("landed", "tollman", 4, train="B", cars=["09"], run="r0")
        self.assertOpen(rid)  # another train's landing is no proof
        self.line("landed", "tollman", 5, train="A", cars=["07"], run="r1")
        self.assertClosed(rid, "fix_order", "train A landed")

    def test_a_redundant_fixed_line_closes_it_alone(self):
        self.line("order", "tollman", 1, train="A", field="07", id="07-fix-1")
        rid = self.add("fix-order", "07", 2, order="07-fix-1", train="A")
        self.line("fixed", "tollman", 3, train="A", field="07", id="07-fix-1", sha="abc", redundant=True)
        self.assertClosed(rid, "fix_order", "redundant")

    def test_the_tollmans_own_fix_closes_when_the_next_train_lands(self):
        self.line("order", "tollman", 1, field="main", id="main-fix-1", branch="tollman-train-fix")
        rid = self.add("fix-order", "main", 2, order="main-fix-1")
        self.line("landed", "tollman", 3, train="A", cars=["07"])  # before its fix: not it
        self.line("fixed", "tollman", 4, field="main", id="main-fix-1", sha="f1")
        self.assertOpen(rid)
        self.line("landed", "tollman", 5, train="B", cars=["tollman"])
        self.assertClosed(rid, "fix_order", "train B landed")

    def test_another_orders_fixed_line_does_not_close_it(self):
        rid = self.add("fix-order", "07", 2, order="07-fix-2", train="A")
        self.line("fixed", "tollman", 3, train="A", field="07", id="07-fix-1", sha="abc")
        self.line("landed", "tollman", 4, train="A", cars=["07"])
        self.assertOpen(rid)


class UserOrder(Store):
    READY = [{"slot": "09", "ready": {"head": "h9"}}]

    def test_an_unhitched_car_closes_once_the_queue_lost_its_mark_and_the_user_line_is_there(self):
        rid = self.add("user-order", "09", 1, order="unhitch", train="A", words="take 09 out")
        self.assertOpen(rid, queue=self.READY)
        self.assertOpen(rid, queue=None)  # the queue could not be read: open
        self.assertOpen(rid, queue=[{"slot": "09"}])  # no mark, but no unhitched line by the user yet
        self.line("unhitched", "09", 2, train="A", why="x", by="tollman")
        self.assertOpen(rid, queue=[{"slot": "09"}])
        self.line("unhitched", "09", 3, train="A", why="x", by="user")
        self.assertClosed(rid, "user_order", "unhitched from train A by the user", queue=[{"slot": "09"}])

    def test_a_wagon_not_riding_closes_on_the_queue_alone(self):
        rid = self.add("user-order", "12", 1, order="unhitch", words="out")
        self.assertOpen(rid, queue=[{"slot": "12", "ready": {"head": "h"}}])
        self.assertClosed(rid, "user_order", "no ready mark of 12", queue=[{"slot": "12"}, *self.READY])

    def test_a_breakup_closes_on_its_trains_cleared_line(self):
        rid = self.add("user-order", "07", 1, order="breakup", train="A", words="break it up")
        self.line("cleared", "07", 2, train="B", why="other")
        self.assertOpen(rid)
        self.line("cleared", "07", 3, train="A", why="the user")
        self.assertClosed(rid, "user_order", "train A cleared")


class HandMerge(Store):
    def cars(self, in_branch, train="A"):
        return {"train": {"train": train}, "cars": [{"field": "07", "head": "h7", "in_branch": in_branch}]}

    def test_open_until_the_car_is_in_the_trains_branch(self):
        rid = self.add("hand-merge", "07", 1, train="A", head="h7")
        self.assertOpen(rid, cars=self.cars(False))
        self.assertOpen(rid, cars=self.cars(True, train="B"))  # another train stands: not this join
        self.assertOpen(rid, cars={"train": None, "cars": []})
        self.assertClosed(rid, "hand_merge", "in the branch of train A", cars=self.cars(True))

    def test_its_train_landing_with_the_field_closes_it(self):
        rid = self.add("hand-merge", "07", 1, train="A", head="h7")
        self.line("landed", "tollman", 2, train="A", cars=["09"])
        self.assertOpen(rid, cars={"train": None, "cars": []})
        self.line("landed", "tollman", 3, train="A", cars=["09", "07"])
        self.assertClosed(rid, "hand_merge", "landed")


class Restart(Store):
    def agent(self, seconds, state="idle"):
        path = str(foreman_wake.field_path(MAIN, "07"))
        return [{"checkout": path, "state": state, "pane_id": "%5", "since": int(at(seconds).timestamp() * 1000)}]

    def test_a_session_restart_closes_on_a_live_session_seen_since(self):
        rid = self.add("restart", "07", 600, of="session")
        self.assertOpen(rid, agents=None)  # the list could not be read
        self.assertOpen(rid, agents=[])
        self.assertOpen(rid, agents=self.agent(600, state="ended"))
        self.assertOpen(rid, agents=self.agent(0))  # a session older than the restart
        self.assertClosed(rid, "restart", "live session (%5", agents=self.agent(610))

    def test_a_train_retry_closes_on_its_next_started_line(self):
        self.line("started", "tollman", 1, train="A", pid=1)
        self.line("retry", "tollman", 2, train="A", why="flaky")
        rid = self.add("restart", "tollman", 2, of="train", train="A")
        self.line("started", "tollman", 3, train="B", pid=2)
        self.assertOpen(rid)
        self.line("started", "tollman", 4, train="A", pid=3)
        self.assertClosed(rid, "restart", "pid 3")


class Question(Store):
    def ask(self, ack, *later):
        mtm_scan.log(MAIN, {"kind": "ask-ack", "slot": "07", "id": ack, "text": "tollman [x]: fix it"}, "tollman")
        for entry in later:
            mtm_scan.log(MAIN, entry, "tollman")
        return self.add("question", "07", 1, ack=ack)

    def test_open_until_done_or_refused(self):
        rid = self.ask("07-a1", {"kind": "ack", "id": "07-a1", "what": "started"})
        self.assertOpen(rid)
        mtm_scan.log(MAIN, {"kind": "ack", "id": "07-a1", "what": "done"}, "tollman")
        self.assertClosed(rid, "question", "ack 07-a1 done")

    def test_a_refusal_closes_it_too(self):
        rid = self.ask("07-a2", {"kind": "ack", "id": "07-a2", "what": "refused"})
        self.assertClosed(rid, "question", "refused")

    def test_its_recorded_void_closes_it_as_void(self):
        rid = self.ask("07-a3", {"kind": "ack-void", "key": "ack-void:07-a3", "what": "void"})
        self.assertClosed(rid, "void", "closed void")


class NeverByAgeOrWord(Store):
    def test_a_year_old_record_without_its_fact_stays_open(self):
        rids = [self.add("fix-order", "07", order="07-fix-9", train="A"),
                self.add("user-order", "09", order="unhitch", train="A", words="w"),
                self.add("hand-merge", "07", train="A", head="h"), self.add("restart", "07", of="session"),
                self.add("restart", "tollman", of="train", train="A"), self.add("question", "07", ack="07-a9")]
        out = self.sweep(400 * 86400, queue=[{"slot": "09", "ready": {"head": "h"}}],
                         cars={"train": None, "cars": []}, agents=[])
        self.assertEqual(out, [])
        self.assertEqual([r["id"] for r in role_records.open_(MAIN, records_kinds.ROLE)], rids)
        with self.assertRaises(ValueError):  # no close by the model's word: only the closer or `user`
            role_records.close(MAIN, records_kinds.ROLE, rids[0], "tollman", "I merged it", "tollman")

    def test_the_queue_is_read_once_per_sweep_and_not_at_all_with_nothing_open(self):
        with mock.patch.object(mtm_scan, "run_json", return_value={"queue": []}) as read:
            self.assertEqual(records_close.run(MAIN, at(1)), [])
            read.assert_not_called()
            self.add("user-order", "09", order="unhitch", words="w")
            self.add("user-order", "12", order="unhitch", words="w")
            self.assertEqual(len(records_close.run(MAIN, at(2))), 2)
        read.assert_called_once()

    def test_a_closer_that_raises_leaves_its_record_open(self):
        rid = self.add("hand-merge", "07", train="A", head="h")
        with mock.patch.object(records_close, "_cars", side_effect=RuntimeError("git gone")):
            self.assertEqual(self.sweep(), [f"{rid} closer failed: git gone"])
        self.assertFalse(self.state(rid)["closed"])


class TickSweeps(Store):
    def tick(self, dry=False, code=0):
        args = argparse.Namespace(repo=MAIN, dry_run=dry, json=True, all_due=False)
        with mock.patch.object(tollman.role_cli, "quiet", return_value=False), \
                mock.patch.object(mtm_scan, "main_checkout", return_value=MAIN), \
                mock.patch.object(tollman.role_cli, "run_tick", return_value=code), \
                mock.patch.object(tollman.role_cli, "after_sync"), \
                mock.patch("board.safely"), mock.patch.object(tollman, "sweep") as sweep:
            self.assertEqual(tollman.tick(args), code)
        return sweep

    def test_a_round_sweeps_a_dry_run_or_a_refused_round_does_not(self):
        self.tick().assert_called_once_with(MAIN, True)
        self.tick(dry=True).assert_not_called()
        self.tick(code=4).assert_not_called()

    def test_the_sweep_prints_one_line_per_close(self):
        self.line("cleared", "07", 2, train="A", why="the user")
        rid = self.add("user-order", "07", 1, order="breakup", train="A", words="w")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tollman.sweep(MAIN, False)
        self.assertTrue(out.getvalue().startswith(f"record {rid} closed by user_order: train A cleared"))
        self.assertTrue(self.state(rid)["closed"])


if __name__ == "__main__":
    unittest.main()
