"""Hal2 plan 0490 step 20 (D20, D21, D23; open-train-brief.md 1), plan 0610 D17 (E4-E6, E8, E10), plan 0687 D1: the
train in its landing. The next train forms on the green merge job of the train before and starts its landing at once;
from that first start its cars are fixed (plan 0687 D1 supersedes plan 0610 D17 for started trains): while its
landing's process waits for that run, and right before the push, a newly hitched wagon does not join (open_train.take
adds no car; its join with a pretest is gone since plan 0687 step 2), a conflict, red light checks, a newer head and a
hand merge neither; it rides the next train. Nothing ever leaves the train (frozen.py, plan 0360 D3) and nothing is
declined. On test_next_train's farm (a bare origin, gh_fake.py's runs)."""
# enforces .adr/merge-queue-policy.md and .adr/tollman.md

import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import next_train
import open_train
import train_state
import trains
from engine_farm import out
from test_farmer import git
from test_next_train import Trains

GREEN = {"state": "green", "lines": []}


class OpenTrain(Trains):
    """Train A (20+02) merged green, its run 720 runs on; train B (03) formed on the new main and waits for it."""

    def setUp(self):
        super().setUp()
        proven = mock.patch.object(trains, "PROVE", lambda *a: GREEN)
        proven.start()
        self.addCleanup(proven.stop)
        self.crop("03", {"three.txt": "3"}, plan="0382-three")
        self.merged()
        self.minute()
        self.b = self.train()
        self.assertEqual(([c["field"] for c in self.b["cars"]], self.b["state"]), (["03"], "landing"))

    def wait(self, polls=1):
        """The landing's wait (next_train.before_push): run 720 concludes after `polls` sleeps; the lines."""
        naps = []

        def sleep(_):
            naps.append(1)
            if len(naps) >= polls:
                self.gh.runs[0] = dict(self.run, status="completed", conclusion="success")

        with contextlib.redirect_stdout(io.StringIO()):
            return next_train.before_push(str(self.cw), sleep=sleep)

    def cars(self):
        return [c["field"] for c in self.train()["cars"]]

    def none_joins(self, lines, field="04"):
        """Plan 0687 D1: the landing's train started, its cars are fixed: no join, the carrier as it was, the wagon
        stays hitched for the next train."""
        self.assertFalse([x for x in lines if "joined" in x], lines)
        self.assertEqual((self.cars(), self.train()["train"], out(self.cw, "rev-parse", "HEAD")),
                         (["03"], self.b["train"], self.before), "the same train, the same cars")
        self.assertFalse([e for e in train_state.lines(str(self.main)) if e["kind"] == "joined"])
        self.assertTrue(self.gate.of(field)["ready"], "it stays hitched")

    def pointer(self):
        return open_train.frozen.POINTERS.read(str(self.cw), open_train.frozen.CURRENT) or ""

    def test_a_wagon_hitched_during_the_wait_does_not_join(self):
        """Plan 0687 D1 superseding plan 0610 D17 for started trains (was: it joins during the wait)."""
        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        self.before, calls = out(self.cw, "rev-parse", "HEAD"), len(self.gate.calls)
        self.none_joins(self.wait())
        self.assertFalse([c for c in self.gate.calls[calls:] if "04" in c], "no mark with it")
        self.assertNotIn("0384-four", self.pointer(), "not in the land run's title")
        hitched = {h["field"]: h for h in json.loads(self.call("cars", "--json")[1])["hitched"]}
        self.assertEqual(hitched["04"]["where"], "next", "`tollman.py cars --json`: it rides the next train")

    def test_a_wagon_hitched_after_the_run_before_concluded_does_not_join_before_the_push(self):
        self.gh.runs[0] = dict(self.run, status="completed", conclusion="success")
        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        self.before = out(self.cw, "rev-parse", "HEAD")
        self.none_joins(self.wait())
        self.assertEqual(open_train.stops(str(self.cw)), 0, "the push goes without it")

    def test_after_the_push_a_wagon_rides_the_next_train(self):
        train_state.append(str(self.main), "push", self.carrier(), train=self.b["train"],
                           head=out(self.cw, "rev-parse", "HEAD"))
        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        self.assertEqual(open_train.take(str(self.cw), str(self.main)), [], "its push started: no join")
        self.assertEqual(self.cars(), ["03"])

    def test_a_conflicting_or_red_wagon_does_not_join_nor_is_it_pretested(self):
        """Was plan 0610 E5, E6: a conflict, red light checks or a red pretest kept nothing out; a started train takes
        none of them, outside its landing neither."""
        self.crop("04", {"three.txt": "four"}, plan="0384-four")  # conflicts with 03 in three.txt
        self.crop("05", {"five.txt": "5"}, plan="0385-five")
        self.before = out(self.cw, "rev-parse", "HEAD")
        with mock.patch.object(trains, "PROVE", lambda main, field, head, barn: {"state": "red", "lines": ["x"]}):
            self.none_joins(self.wait(polls=2))
            self.assertEqual((self.train()["state"], open_train.stops(str(self.cw))), ("landing", 0))
            self.round()
        self.none_joins([], "05")

    def test_a_riding_car_s_newer_head_does_not_join(self):
        """Was plan 0610 E10: 03 hitched again on a newer head while its train waits: its car keeps its head."""
        path, old = self.fields["03"], self.b["cars"][0]["head"]
        (path / "three.txt").write_text("3, newer")
        git(path, "commit", "-qam", "three, newer")
        git(path, "push", "-q", "origin", "HEAD")
        self.gate.of("03")["ready"] = dict(self.gate.of("03")["ready"], head=out(path, "rev-parse", "HEAD"))
        self.before = out(self.cw, "rev-parse", "HEAD")
        self.none_joins(self.wait(), "03")
        self.assertEqual(self.train()["cars"][0]["head"], old)

    def test_a_hand_merge_into_a_started_carrier_is_no_car(self):
        """Was plan 0610 E8: a head merged into the carrier by hand after the first start is not recorded."""
        four = self.crop("04", {"four.txt": "4"}, plan="0384-four")
        git(self.cw, "merge", "-q", "--no-ff", "-m", "by hand", four["ready"]["head"])
        self.before = out(self.cw, "rev-parse", "HEAD")
        with mock.patch.object(trains, "PROVE", side_effect=AssertionError("no draft on a started train")):
            self.none_joins(self.wait())

    def test_a_train_whose_car_rides_alone_takes_nobody(self):
        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        with mock.patch.object(open_train.gate_car, "alone_why", lambda main, default, head: "it adds the workflow"):
            self.wait()
        self.assertEqual(self.cars(), ["03"])

    def test_an_alone_wagon_hitched_in_the_landing_is_owed_the_very_next_train(self):
        """Plan 0687 step 2: the landing's round (open_train.take) adds no car, it only owes an alone car (D15)."""
        four = self.crop("04", {"four.txt": "4"}, plan="0384-four")
        self.before = out(self.cw, "rev-parse", "HEAD")
        alone = lambda main, default, head: "it adds the workflow" if head == four["ready"]["head"] else None  # noqa: E731
        with mock.patch.object(open_train.gate_car, "alone_why", alone):
            self.none_joins(self.wait())
        self.assertEqual([e["field"] for e in train_state.lines(str(self.main)) if e["kind"] == "alone"], ["04"])


class Fold(unittest.TestCase):
    def test_a_joined_car_counts_a_newer_head_takes_its_place_and_a_declined_head_is_read(self):
        rows = [{"kind": "formed", "train": "B", "cars": [{"field": "03"}]}, {"kind": "started", "train": "B", "pid": 1},
                {"kind": "joined", "train": "B", "cars": [{"field": "04"}]},
                {"kind": "declined", "train": "B", "field": "05", "head": "abc1234"}]
        b = train_state.standing(rows)
        self.assertEqual(([c["field"] for c in b["cars"]], b["state"], b["declined"]),
                         (["03", "04"], "landing", [{"field": "05", "head": "abc1234"}]))
        rows.append({"kind": "joined", "train": "B", "cars": [{"field": "03", "head": "newer"}]})  # plan 0610 E10
        self.assertEqual(train_state.standing(rows)["cars"], [{"field": "03", "head": "newer"}, {"field": "04"}])


if __name__ == "__main__":
    unittest.main()
