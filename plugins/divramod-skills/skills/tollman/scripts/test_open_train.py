"""Hal2 plan 0610 step 3 (D8, D17; audit E3-E6, E8, E10), plan 0687 D1: a wagon that hitches while a train stands
joins it (open_train.joiners, `tollman.py join`, train_join.record) only while that train never started (formed:
test_engine's form-died train); once it started (red, fixing, retry here) its cars are fixed: no join, a conflict,
red light checks, a riding car's newer head and a hand merge neither, the hand's `join` refused; an alone car is still
owed the very next train (D15). `tollman.py cars --json` says where every hitched wagon stands. Whole rounds on
engine_farm.py's farm; train 56's replay: test_open_train_fixed.py."""
# enforces .adr/tollman.md and .adr/hitch-is-forever.md

import json
import subprocess
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import train_state
import trains
from engine_farm import Farm, out
from test_farmer import git


def out_code(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True).returncode

GREEN = {"state": "green", "lines": []}
RUN = "https://github.com/x/runs/9"


class RedTrain(Farm):
    """Train 07+09 lands, goes red and stands: it started once, its cars are fixed (plan 0687 D1)."""

    def setUp(self):
        super().setUp()
        proven = mock.patch.object(trains, "PROVE", lambda *a: GREEN)
        proven.start()
        self.addCleanup(proven.stop)
        self.crop("07", {"seven.txt": "7"}, plan="0294-tollman-role")
        self.crop("09", {"nine.txt": "9"})
        self.round()
        self.ends({"status": "gate_failed", "run": RUN, "red": [{"name": "linux / rust-test"}]})
        self.gate.of(self.carrier()).update(state="held", train=None, hold={"reason": "failed"})
        self.round()
        self.assertEqual((self.train()["state"], self.train()["starts"]), ("red", 1))

    def cars(self):
        return [c["field"] for c in self.train()["cars"]]

    def joined(self):
        return [e for e in train_state.lines(str(self.main)) if e["kind"] == "joined"]

    def joins(self):
        return [a for a in self.last if a[0] == "join"]

    def lands_alone(self, new):
        """The retry starts 07+09 only, `new` (a head hitched after the first start) not merged."""
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 0)
        self.round()
        self.assertEqual((self.train()["state"], self.cars()), ("landing", ["07", "09"]))
        self.assertNotEqual(out_code(self.cw, "merge-base", "--is-ancestor", new, "HEAD"), 0, "never merged")


class Open(RedTrain):
    """The wagons hitched after the red start do not join it (plan 0687 D1, superseding plan 0610 D17 for started
    trains); an alone car is still owed the very next train (D15)."""

    def test_a_wagon_hitched_while_the_train_is_red_does_not_join(self):
        """Plan 0687 D1 (was E3, E4): red, then retry: no join is recorded, the restart lands 07+09 only."""
        eleven = self.crop("11", {"eleven.txt": "11"}, plan="0611-eleven")
        head = out(self.cw, "rev-parse", "HEAD")
        self.round()
        self.assertEqual((self.joins(), self.cars(), self.joined(), out(self.cw, "rev-parse", "HEAD")),
                         ([], ["07", "09"], [], head), "nothing joins, the carrier as it was")
        mark = self.gate.of(self.carrier()).get("train") or {}
        self.assertNotIn("11", {c["field"] for c in mark.get("cars", [])}, "not on the queue's mark")
        self.lands_alone(eleven["ready"]["head"])
        self.assertTrue(self.gate.of("11")["ready"], "11 stays hitched")

    def test_an_alone_car_hitched_while_the_train_stands_rides_alone_in_the_very_next_train(self):
        """D15 (step 10): a wagon that would ride alone and hitches while a train stands goes on that train's
        `alone_next` (an `alone` line); after the barn it rides alone at once, ahead of a later hitch, without the
        minimum."""
        self.crop("13", {".github/workflows/merge-to-main.yml": "on: push\n"})
        self.round()
        self.assertEqual((self.last, self.cars()), ([("join", "run", "-")], ["07", "09"]), "it does not join")
        owed = [e for e in train_state.lines(str(self.main)) if e["kind"] == "alone"]
        self.assertEqual([(e["field"], e["train"]) for e in owed], [("13", self.train()["train"])])
        self.assertEqual(trains.owed(train_state.lines(str(self.main))), ["13"])
        self.round()
        self.assertEqual(len([e for e in train_state.lines(str(self.main)) if e["kind"] == "alone"]), 1, "once")
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 0)
        self.round()
        thirteen = self.gate.of("13")
        self.ends({"status": "landed", "commit": "c0ffee"}, land=True)
        self.gate.tickets.append(thirteen)  # the landing took only its cars' tickets
        self.crop("11", {"eleven.txt": "11"})  # hitched after 13
        with mock.patch.object(trains, "MIN_HITCHED", 10):
            self.round()
        self.assertEqual(self.cars(), ["13"], "13 rides alone in the very next train, ahead of 11")
        self.assertEqual(self.train()["number"], 2)
        self.assertTrue(self.gate.of("11")["ready"], "11 waits, hitched")

    def test_a_conflicting_wagon_does_not_join_a_started_train(self):
        """Plan 0687 D1 (was E5 outside a landing): a conflicting wagon stays out; the restart does not wait for it."""
        eleven = self.crop("11", {"nine.txt": "eleven"})  # conflicts with car 09
        self.round()
        self.assertEqual((self.joins(), self.cars()), ([], ["07", "09"]))
        self.lands_alone(eleven["ready"]["head"])

    def test_a_wagon_with_red_light_checks_does_not_join_and_gets_no_order_in_the_train(self):
        """Plan 0687 D1 (was E5, plan 0620 D6): red light checks keep nothing out of a train that never started; a
        started one takes no car, so no fix order is placed in it, and its retry restarts past it."""
        eleven = self.crop("11", {"eleven.txt": "11"})
        with mock.patch.object(trains, "PROVE", lambda main, field, head, barn: {
                "state": "red", "lines": ["names: eleven.txt"]} if field.endswith("/11") else GREEN):
            self.round()
            self.assertEqual((self.joins(), self.cars()), ([], ["07", "09"]))
            self.round()
            self.assertFalse([e for e in train_state.lines(str(self.main)) if e["kind"] == "order"], "no order")
            self.lands_alone(eleven["ready"]["head"])

    def test_a_riding_car_s_newer_head_does_not_join(self):
        """Plan 0687 D1 (was E10): 09 hitched again on a newer head while its train is red: its car keeps its head,
        the restart lands the old one; the newer head rides the next train."""
        path, old = self.fields["09"], self.train()["cars"][1]["head"]
        (path / "nine.txt").write_text("9, newer")
        git(path, "commit", "-qam", "nine, newer")
        git(path, "push", "-q", "origin", "HEAD")
        new = out(path, "rev-parse", "HEAD")
        self.gate.of("09")["ready"] = dict(self.gate.of("09")["ready"], head=new)
        self.round()
        self.assertEqual((self.joins(), self.cars(), self.train()["cars"][1]["head"]), ([], ["07", "09"], old))
        self.lands_alone(new)

    def test_a_hand_merge_into_a_started_carrier_is_no_car(self):
        """Plan 0687 D1 (was E8): a head merged into a started carrier by hand is not recorded as a car (nothing
        joins); `cars` shows it `in-branch`."""
        eleven = self.crop("11", {"eleven.txt": "11"})
        git(self.cw, "merge", "-q", "--no-ff", "-m", "by hand", eleven["ready"]["head"])
        with mock.patch.object(trains, "PROVE", side_effect=AssertionError("no draft runs on a started train")):
            self.round()
        self.assertEqual((self.joins(), self.cars(), self.joined()), ([], ["07", "09"], []))

    def test_join_by_hand_is_refused_once_the_train_started(self):
        """Plan 0687 D1 (was D8a): `tollman.py join <field>` refuses a started train before it touches anything."""
        eleven = self.crop("11", {"eleven.txt": "11"})
        ticket, calls = json.dumps(eleven, sort_keys=True), len(self.gate.calls)
        for field in ("11", "12"):
            code, text = self.call("join", field)
            self.assertEqual(code, 1, text)
            self.assertIn("rides the next train", text)
        self.assertEqual((self.cars(), self.joined(), len(self.gate.calls)), (["07", "09"], [], calls))
        self.assertEqual(json.dumps(self.gate.of("11"), sort_keys=True), ticket, "11 stays hitched, as it was")

    def test_cars_says_where_every_hitched_wagon_stands(self):
        """D8b: the cars and every hitched wagon from the queue, the train state and the train's branch; a started
        train is not open, a later hitch rides the next train (plan 0687 D1)."""
        eleven = self.crop("11", {"eleven.txt": "11"})
        self.crop("12", {"twelve.txt": "12"})
        (self.fields["12"] / "plans").mkdir(exist_ok=True)
        (self.fields["12"] / "plans/LEAD").write_text("13\n")
        git(self.cw, "merge", "-q", "--no-ff", "-m", "by hand", eleven["ready"]["head"])
        code, text = self.call("cars", "--json")
        self.assertEqual(code, 0, text)
        d = json.loads(text)
        self.assertEqual((d["schema"], d["train"]["state"], d["train"]["open"], d["train"]["pushed"]),
                         (1, "red", False, False))
        self.assertEqual([(c["field"], c["in_branch"]) for c in d["cars"]], [("07", True), ("09", True)])
        where = {h["field"]: (h["where"], h.get("reason")) for h in d["hitched"]}
        self.assertEqual(where, {"07": ("car", None), "09": ("car", None), "11": ("in-branch", None),
                                 "12": ("waits", "servant")})
        git(self.cw, "reset", "-q", "--hard", "HEAD^")
        hitched = {h["field"]: h for h in json.loads(self.call("cars", "--json")[1])["hitched"]}
        self.assertEqual(hitched["11"]["where"], "next")
        self.assertIn("its cars are fixed (plan 0687 D1)", hitched["11"]["why"])
        self.round()
        d = json.loads(self.call("cars", "--json")[1])
        self.assertEqual(([c["field"] for c in d["cars"]], {h["field"]: h["where"] for h in d["hitched"]}["11"]),
                         (["07", "09"], "next"))
        self.assertIn("hitched 11", self.call("cars")[1])


class Pushed(Farm):
    """After the push nothing joins: the wagon rides the next train (D17)."""

    def test_a_wagon_hitched_after_the_push_rides_the_next_train(self):
        with mock.patch.object(trains, "PROVE", lambda *a: GREEN):
            self.crop("07", {"seven.txt": "7"})
            self.round()
            self.alive.add(40001)
            train_state.append(str(self.main), "push", self.carrier(), train=self.train()["train"],
                               head=out(self.cw, "rev-parse", "HEAD"))
            self.crop("11", {"eleven.txt": "11"})
            code, text = self.call("join", "11")
            self.assertEqual(code, 1, text)
            self.assertIn("rides the next train", text)
            self.round()
            self.assertEqual([c["field"] for c in self.train()["cars"]], ["07"])
            hitched = {h["field"]: h["where"] for h in json.loads(self.call("cars", "--json")[1])["hitched"]}
            self.assertEqual(hitched["11"], "next")


if __name__ == "__main__":
    unittest.main()
