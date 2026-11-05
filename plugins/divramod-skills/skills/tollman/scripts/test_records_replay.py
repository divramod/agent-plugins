"""Hal2 plan 0611 step 8 (design.md §6): a clear mid-train loses nothing. A red train of the cars 07 and 09 with
five open records (a fix order, a hand merge, a user order, a question, a standing order); everything in memory is
dropped (a "clear": the state and the handoff check read the disk only); `state_cmd.of` and `handoff.records_problems`
then name every open record, and the closers' facts, fed one by one, close exactly their record."""

import json
import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import handoff
import mtm_scan
import records_kinds
import role_records
import standing
import state_cmd
import tollman
import train_state
from test_orders import RUN, Red

WORDS = "the user, 2026-11-05: at least 10 wagons"
ROLE = records_kinds.ROLE


class Replay(Red):
    def setUp(self):
        super().setUp()
        main = str(self.main)
        self.train_name = self.train()["train"]
        self.assertEqual(self.call("order", "07", "--why", "its test fails", "--run", RUN)[0], 0)
        self.hand = records_kinds.add(main, "hand-merge", "12", "hand merge of 12", train=self.train_name, head="h12")["id"]
        self.user = records_kinds.add(main, "user-order", "09", "unhitch 09", order="unhitch",
                                      train=self.train_name, words=WORDS)["id"]
        mtm_scan.log(main, {"kind": "ask-ack", "slot": "16", "id": "16-1", "text": "tollman [x]: fix it"}, "tollman")
        self.ask = records_kinds.add(main, "question", "16", "question to 16", ack="16-1")["id"]
        self.stand = standing.add(main, "minimum", 10, WORDS)["id"]
        self.fix = "R1"

    def clear(self):
        """A new process: nothing in memory, the handoff empty. Returns the state read from disk."""
        return state_cmd.of(str(self.main))

    def ids(self):
        return [r["id"] for r in role_records.open_(str(self.main), ROLE)]

    def problems(self, text):
        f = handoff.path(str(self.main), tollman.WIRING)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        return handoff.records_problems(str(self.main), tollman.WIRING)

    def sweep(self, **facts):
        return role_records.sweep(str(self.main), ROLE, None, {"queue": [{"slot": "09", "ready": {"head": "h"}}],
                                                               "cars": {"train": None, "cars": []}, "agents": [], **facts})

    def test_a_clear_loses_no_record_no_car_and_no_standing_order(self):
        before = json.loads(json.dumps(state_cmd.of(str(self.main))))
        after = self.clear()
        everything = {self.fix, self.hand, self.user, self.ask, self.stand}
        self.assertEqual({r["id"] for r in after["records"]}, everything - {self.stand})  # the order is under standing
        self.assertEqual(after, before)
        self.assertEqual([c["field"] for c in after["cars"]], ["07", "09"])
        self.assertEqual([s["id"] for s in after["standing"]], [self.stand])
        bad = self.problems("A fresh handoff naming nothing.\n")
        self.assertEqual(len(bad), 5, bad)
        self.assertTrue(all("is open and not named" in b for b in bad), bad)
        self.assertEqual(self.problems(" ".join(f"{i} stands." for i in sorted(everything)) + "\n"), [])

    def test_each_record_closes_only_on_its_own_fact(self):
        self.clear()
        main = str(self.main)
        self.assertEqual(self.sweep(), [])  # no fact yet: all five stay open
        self.assertEqual(len(self.ids()), 5)
        # the question: its ack arrives
        mtm_scan.log(main, {"kind": "ack", "id": "16-1", "what": "done"}, "tollman")
        self.assertEqual([x.split(":")[0] for x in self.sweep()], [f"{self.ask} closed by question"])
        # the hand merge: the car is in the train branch
        cars = {"train": {"train": self.train_name}, "cars": [{"field": "12", "in_branch": True, "head": "h12"}]}
        self.assertEqual([x.split(":")[0] for x in self.sweep(cars=cars)], [f"{self.hand} closed by hand_merge"])
        # the user order: the queue lost the mark and the user's unhitched line is there
        gone = [{"slot": "07"}]
        self.assertEqual(self.sweep(queue=gone), [])  # no user line yet
        train_state.append(main, "unhitched", "09", train=self.train_name, why="x", by="user")
        self.assertEqual([x.split(":")[0] for x in self.sweep(queue=gone)], [f"{self.user} closed by user_order"])
        # the fix order: fixed, then the train landed
        train_state.append(main, "fixed", "07", train=self.train_name, field="07", id="07-fix-1", sha="abc")
        self.assertEqual(self.sweep(), [])  # merged, not landed
        train_state.append(main, "landed", "tollman", train=self.train_name, cars=["07"], run="r1")
        self.assertEqual([x.split(":")[0] for x in self.sweep()], [f"{self.fix} closed by fix_order"])
        # the standing order closes by no code: only the user's revoke
        self.assertEqual(self.ids(), [self.stand])
        self.assertTrue(standing.revoke(main, self.stand, "the user: revoked"))
        self.assertEqual(self.ids(), [])


if __name__ == "__main__":
    unittest.main()
