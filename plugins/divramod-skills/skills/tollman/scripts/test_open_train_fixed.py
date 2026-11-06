"""Hal2 plan 0687 D1, D4 (tollman learning L255, train 56): a train's cars are fixed at its first start. Train 56
started once and went red; wagons hitched after it joined it and rode its retry. Now a wagon hitched after the first
start gets no join in the round, the hand's `tollman.py join <field>` is refused ("rides the next train"), the field
stays hitched and rides the next train after the barn; a `joined` line recorded before the cut still merges at the
restart (D4). Whole rounds on engine_farm.py's farm (test_open_train.RedTrain)."""
# enforces .adr/tollman.md and .adr/hitch-is-forever.md

import json
import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import open_train
import train_state
from engine_farm import out
from test_open_train import RedTrain


class Train56(RedTrain):
    def test_a_wagon_hitched_after_the_first_start_rides_the_next_train(self):
        eleven = self.crop("11", {"eleven.txt": "11"}, plan="0611-eleven")
        ticket = json.dumps(eleven, sort_keys=True)
        self.round()
        self.assertEqual((self.joins(), self.cars(), self.joined()), ([], ["07", "09"], []), "no join action")
        code, text = self.call("join", "11")
        self.assertEqual(code, 1, text)
        self.assertIn("rides the next train", text)
        self.assertEqual(json.dumps(self.gate.of("11"), sort_keys=True), ticket, "hitched, its ticket unchanged")
        self.lands_alone(eleven["ready"]["head"])
        first = self.train()["number"]
        self.ends({"status": "landed", "commit": "c0ffee"}, land=True)
        self.gate.tickets.append(eleven)  # the landing took only its cars' tickets
        self.round()
        self.assertEqual((self.cars(), self.train()["number"]), (["11"], first + 1), "11 rides the next train")

    def test_a_join_recorded_before_the_cut_still_merges_at_the_restart(self):
        """D4: train 56 keeps the cars recorded as joined; engine.restart (resolve_train.merge_rest) merges them."""
        eleven = self.crop("11", {"eleven.txt": "11"})
        car = {"field": "11", "branch": "11", "head": eleven["ready"]["head"], "plan": ""}
        head = out(self.cw, "rev-parse", "HEAD")
        train_state.append(str(self.main), "joined", self.carrier(), train=self.train()["train"], cars=[car],
                           base=head, commit=head, merged=False, result="none", why="joined while red")
        self.round()
        self.assertEqual((self.joins(), self.cars()), ([], ["07", "09", "11"]), "it rides, nothing new joins")
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 0)
        self.round()
        self.assertEqual((self.train()["state"], self.cars()), ("landing", ["07", "09", "11"]))
        self.assertEqual(out(self.cw, "merge-base", "--is-ancestor", car["head"], "HEAD"), "", "merged by the restart")


class Cut(unittest.TestCase):
    def test_a_started_train_drafts_nothing_a_formed_one_still_may(self):
        """The cut is `starts` (train_fold: every `started` line raises it, the first too); formed: test_engine's
        test_a_train_whose_form_died_resumes_with_its_own_cars takes a joiner."""
        rows = [{"kind": "formed", "train": "B", "cars": [{"field": "03", "head": "a" * 40}]}]
        formed = train_state.standing(rows)
        started = train_state.standing([*rows, {"kind": "started", "train": "B", "pid": 1}])
        self.assertEqual((open_train.fixed(formed), open_train.fixed(started), started["starts"]), (False, True, 1))
        self.assertIsNone(open_train.draft("", "", started, [{"slot": "04", "ready": {"head": "b" * 40}}], None))
        self.assertEqual(open_train.round_of("", "", {**started, "cars": []}, [], None), ([], []))


if __name__ == "__main__":
    unittest.main()
