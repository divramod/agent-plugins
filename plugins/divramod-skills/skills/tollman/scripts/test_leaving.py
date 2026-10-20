"""Hal2 plan 0294 step 12, the second restock: the barn's leaving ticket (hal2 plan 0263 D129) in the queue the train
engine reads. A head's ticket that ended stays held until no run of its worktree goes; `worktree queue --json` shows
it as `state: held` with `waits_for`. It is no car and no place the planner waits for: only a waiter's look frees
it, and the hitched have no process, so the train forms and its carrier's landing waits behind it. The tollman's own leaving ticket (its last train's run still goes) is neither a landing of its own nor a hold to release."""

import json
import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import test_trains
import trains
from engine_farm import OWN, Farm

AT = test_trains.AT
TOP = "/no/such/farm/tollman-hal2"

WHY = "run 9 of hal2/05 is still queued or in progress"


def leaving(field, worktree, pos=0, **kw):
    """A ticket as `worktree queue --json` lists one that ended (hal2-git's `queue::runs`)."""
    return {"slot": field, "position": pos, "state": "held", "branch": field, "worktree": str(worktree), "seq": pos + 1,
            "pid": 4711, "hold": {"reason": "reserved", "message": "ended; held until its worktree's runs have ended"},
            "waits_for": WHY, "reserved": None, "ready": None, "train": None, "rides_with": None, **kw}


class Draft(test_trains.Crops):
    def test_a_leaving_ticket_in_front_holds_no_train_back_and_is_no_car(self):
        q = self.queue(**{"07": {"seven.txt": "7"}, "09": {"nine.txt": "9"}})
        front = leaving("05", self.d, reserved={"by": "the user", "since": AT})
        tickets = [front] + [dict(t, position=t["position"] + 1) for t in q]
        self.assertIsNone(trains.held_for(tickets, "tollman-hal2"), "no place that waits for its field")
        d = self.draft(tickets)
        self.assertEqual((self.cars(d), d["waiting"], d["unhitched"]), (["07", "09"], [], []))
        # A ready mark it still bore would make it no wagon: its own landing ended, a run of its may still land it.
        marked = dict(front, ready={"at": AT, "head": q[0]["ready"]["head"], "by": "hal2/05"})
        d = self.draft([marked] + tickets[1:])
        self.assertEqual((self.cars(d), d["waiting"], d["unhitched"]), (["07", "09"], [], []))


class Carrier(unittest.TestCase):
    """The state machine over data, as test_trains.Plan: the field does not exist, so nothing is drafted."""

    def plan(self, tickets):
        return trains.plan(TOP, "/no/such/farm", tickets, [], {}, alive=lambda pid: pid == 4711,
                           result=lambda main: None)

    def test_the_tollman_s_own_leaving_ticket_is_no_landing_of_its_own(self):
        mark = {"carrier": "tollman-hal2", "cars": [{"field": "05"}], "at": AT}
        mine = leaving("tollman-hal2", TOP, train=mark)
        self.assertEqual(self.plan([dict(mine, waits_for=None, state="active")]), [],
                         "a landing of the field that runs is never touched")
        left = self.plan([mine])  # the pid of a leaving ticket is no landing's, whoever has it now
        self.assertEqual((test_trains.shape(left), left[0]["argv"][4]),
                         ([("breakup", "run", "-")], "a mark without a train of ours"))


class Rounds(Farm):
    def test_a_train_forms_behind_a_leaving_ticket_and_behind_the_tollman_s_own(self):
        self.gate.ticket("05", self.field("05"), state="held", pid=4711, waits_for=WHY,
                         hold={"reason": "reserved", "message": "ended; held until its worktree's runs have ended"})
        self.gate.ticket(self.carrier(), self.wm, state="held", pid=4712, waits_for=WHY, hold={"reason": "failed", "step": "gate"})
        self.alive.update({4711, 4712})  # pids another process got: a leaving ticket's landing ended all the same
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        d = json.loads(self.call("train", "--dry-run", "--json", repo=self.main)[1])
        self.assertEqual(([c["field"] for c in d["cars"]], d["waiting"], d["unhitched"]), (["07", "09"], [], []))
        self.round()
        self.assertEqual((self.last, self.spawned), ([("form", "run", "-")], [self.carrier()]))
        self.assertEqual(self.gate.calls, [["worktree", "queue", "train", self.carrier(), "07", "09", "--train", "1", "--attempt", "1"]],
                         "marked on its one ticket, nothing released")
        self.assertEqual([(t["slot"], bool(t.get("waits_for"))) for t in self.gate.tickets if t["state"] == "held"],
                         [("05", True), (OWN, True)], "the train rides in its own worktree's ticket (plan 0375 D5)")

    def test_a_breakup_releases_a_failed_hold_but_never_a_leaving_ticket(self):
        mine = self.gate.ticket(self.carrier(), self.wm, state="held", waits_for=WHY, hold={"reason": "reserved"})
        mine["train"] = {"carrier": self.carrier(), "cars": [{"field": "05"}], "at": AT}
        self.round()
        self.assertEqual((self.last, self.gate.calls), ([("breakup", "run", "-")],
                                                        [["worktree", "queue", "train", self.carrier(), "--clear"]]))
        self.assertIs(self.gate.of(self.carrier()), mine, "it goes by itself once its run has ended")
        mine.update(waits_for=None, hold={"reason": "failed", "step": "gate"},
                    train={"carrier": self.carrier(), "cars": [{"field": "06"}], "at": "2026-10-13T11:00:00Z"})
        self.round()
        self.assertEqual(self.gate.calls[1:], [["worktree", "queue", "train", self.carrier(), "--clear"],
                                               ["worktree", "release", self.carrier(), "--by", "the user"]])


if __name__ == "__main__":
    unittest.main()
