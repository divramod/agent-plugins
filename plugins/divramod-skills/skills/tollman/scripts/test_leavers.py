"""Hal2 plan 0383 step 3 (D3, D14): a ticket that leaves the merge queue unmerged is put back on its place, its
foreman told to return and the trains behind it hold. Real git (test_trains.Crops), the queue as data."""
# enforces .adr/merge-queue-policy.md

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import leavers
import test_trains as tt
import trains

TOP = "/no/such/farm/tollman-hal2"
PANES = {"02": "%5"}


def head(field, worktree, pos=0, **kw):
    """A ticket with a process (a landing) of `field`."""
    return {"slot": field, "position": pos, "state": "active", "holding": True, "pid": os.getpid(), "seq": 7,
            "branch": field, "worktree": str(worktree), "ready": None, "reserved": None, "hold": None, "train": None,
            "rides_with": None, **kw}


class Leavers(tt.Crops):
    def setUp(self):
        super().setUp()
        self.state = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.state, True)
        folder = mock.patch.object(leavers, "folder", lambda main: self.state)
        folder.start()
        self.addCleanup(folder.stop)
        barn = mock.patch.object(trains, "default_ref", lambda repo: "main")  # the test repository has no origin
        barn.start()
        self.addCleanup(barn.stop)
        self.wt = self.field("02", {"two.rs": "2\n"})
        cars = self.queue(**{"05": {"five.rs": "5\n"}, "07": {"seven.rs": "7\n"}})
        self.cars = [dict(c, position=n + 1) for n, c in enumerate(cars)]

    def field(self, name, files):
        """A field's own worktree on its own crop (one commit past the barn)."""
        self.write(name, files)
        self.g("checkout", "-q", "main")
        path = Path(tempfile.mkdtemp()) / name
        self.g("worktree", "add", "-q", str(path), name)
        self.addCleanup(shutil.rmtree, path.parent, True)
        return path

    def check(self, tickets, priority=(), panes=None, **kw):
        return leavers.check(self.d, TOP, list(tickets), list(priority), panes or {}, "main", **kw)

    def plan(self, tickets, left):
        return trains.plan(TOP, self.d, list(tickets), [], {}, alive=lambda pid: False, result=lambda m: None,
                           left=left)

    def kinds(self, out):
        return [(a["kind"], a["do"], a["slot"]) for a in out]


class Replay(Leavers):
    """Field 02 ran `worktree stop` and `gh run cancel` while the train of 05 and 07 waited behind it (L36)."""

    def test_the_stopped_and_cancelled_ticket_comes_back_and_the_train_behind_it_holds(self):
        first = self.check([head("02", self.wt)] + self.cars)
        self.assertEqual((first["actions"], first["held"]), ([], None), "the first pass only looks")
        free = self.plan([head("02", self.wt)] + self.cars, None)
        self.assertEqual([a["kind"] for a in free if a["do"] == "run"], ["form"], "without the hold the cars ride")
        second = self.check(self.cars, panes=PANES)  # 02's ticket is gone, its crop is not in the barn
        order, tell, note = second["actions"]
        self.assertEqual(order["argv"][:6], ["hal2-cli-git", "worktree", "queue", "order", "02", "--by"])
        self.assertIn("queue watch: 02 returned", order["argv"][6])
        self.assertEqual((tell["do"], tell["slot"], tell["pane"]), ("send", "02", "%5"))
        self.assertIn("/merge-to-main", tell["text"])
        self.assertEqual((note["do"], note["kind"]), ("record", "queue-leaver"))
        self.assertEqual((second["held"], [g["slot"] for g in second["gone"]]), ("02", ["02"]))
        held = self.plan(self.cars, second["held"])
        self.assertEqual([a for a in held if a["do"] == "run"], [], "train 20 holds: nothing forms, nothing lands")
        d = trains.draft(self.d, self.cars, "tollman-hal2", "main", "main", left="02")
        self.assertEqual((d["cars"], [w["field"] for w in d["waiting"]]), ([], ["05", "07"]))
        self.assertIn("never given up", d["waiting"][0]["why"])
        again = self.check(self.cars, panes=PANES)  # the order did not run yet: the same keys, a keyed retry
        self.assertEqual([a["key"] for a in again["actions"]], [a["key"] for a in second["actions"]])
        back = dict(head("02", self.wt), state="held", pid=0, holding=True,
                    reserved={"by": order["argv"][6], "since": "2026-10-19T01:00:00Z"})
        third = self.check([back] + self.cars)  # the ticket is back, reserved by the watch
        self.assertEqual((third["actions"], third["held"]), ([], "02"), "nothing to put back, the trains still hold")
        taken = self.check([head("02", self.wt)] + self.cars)  # 02's merge-to-main took the place over
        self.assertEqual((taken["actions"], taken["held"]), ([], None), "in motion again: the trains go")

    def test_the_order_puts_a_head_in_front_and_a_listed_slot_back_where_it_was(self):
        self.assertEqual(leavers.new_order([], ["16"], [{"slot": "02", "position": 0}]), ["02", "16"])
        self.assertEqual(leavers.new_order(["18", "02", "16"], ["18", "16"], [{"slot": "02", "position": 3}]),
                         ["18", "02", "16"])
        self.assertEqual(leavers.new_order(["02", "16"], ["16"], [{"slot": "02", "position": 2}]), ["02", "16"])
        self.assertEqual(leavers.new_order([], ["16"], [{"slot": "02", "position": 4}]), ["16", "02"])
        self.assertEqual(leavers.new_order([], [], [{"slot": "09", "position": 2}, {"slot": "02", "position": 0}]),
                         ["02", "09"])
        order = self.check(self.cars, priority=["16"], panes=PANES)
        self.assertEqual(order["actions"], [], "nothing seen before: nothing left")
        self.check([head("02", self.wt, 1)] + self.cars, priority=["16"])
        gone = self.check(self.cars, priority=["16"])
        self.assertEqual(gone["actions"][0]["argv"][4:6], ["16", "02"], "a waiter is listed behind the others")


class NoLeaver(Leavers):
    def seen_then_gone(self, ticket, **kw):
        self.check([ticket] + self.cars)
        return self.check(self.cars, **kw)

    def test_a_landed_ticket_is_no_leaver(self):
        self.g("checkout", "-q", "main")
        self.g("merge", "-q", "--ff-only", "02")
        out = self.seen_then_gone(head("02", self.wt))
        self.assertEqual((out["actions"], out["held"]), ([], None), "its head is in the barn")

    def test_a_pure_hitch_the_tollman_unhitched_is_no_leaver(self):
        hitched = dict(self.cars[0], slot="09", worktree=str(self.wt))
        out = self.seen_then_gone(hitched)
        self.assertEqual((out["actions"], out["held"]), ([], None))

    def test_the_tollman_a_servant_and_a_removed_field_are_no_leavers(self):
        servant = head("31", self.servant_field())  # D16: a servant by its plans/LEAD
        for ticket in (head("tollman-hal2", self.wt), servant, head("02", "/no/such/field")):
            out = self.seen_then_gone(ticket)
            self.assertEqual((ticket["slot"], out["actions"], out["held"]), (ticket["slot"], [], None))

    def test_an_explicit_release_lets_the_place_go_once(self):
        self.check([head("02", self.wt)] + self.cars)
        leavers.release(self.d, "02")
        self.assertEqual(self.check(self.cars)["actions"], [], "the user's or the farmer's word")
        self.assertEqual(leavers.read(self.d, leavers.RELEASED, None)["slots"], [], "the word is used up")
        self.check([head("02", self.wt)] + self.cars)
        self.assertEqual(self.check(self.cars)["held"], "02", "the next time it is a leaver again")

    def test_a_dry_look_writes_nothing(self):
        self.check([head("02", self.wt)] + self.cars, dry=True)
        self.assertEqual(list(self.state.iterdir()), [])


class Stopped(Leavers):
    def test_a_stopped_ticket_keeps_its_place_tells_its_foreman_once_and_holds_the_trains(self):
        stopped = head("02", self.wt, state="held", pid=0, hold={"reason": "interrupted", "step": "stopped"})
        out = self.check([stopped] + self.cars, panes=PANES)
        send, note = out["actions"]
        self.assertEqual((send["do"], send["pane"], out["held"]), ("send", "%5", "02"))
        self.assertIn("stopped", send["text"])
        self.assertFalse([a for a in out["actions"] if a["do"] == "run"], "nothing to put back: it is in its place")
        self.assertFalse([a for a in self.plan([stopped] + self.cars, out["held"]) if a["do"] == "run"])
        self.assertEqual(self.check([stopped] + self.cars, panes=PANES)["actions"][0]["key"], send["key"])


if __name__ == "__main__":
    unittest.main()
