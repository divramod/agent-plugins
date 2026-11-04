"""Hal2 plan 0610 step 3 (D8, D17; audit E3-E6, E8, E10): a wagon that hitches while a train stands outside its landing
(formed, resolving, red, fixing, retry) joins it by the round's join (open_train.joiners, `tollman.py join`,
train_join.record) and its next start merges it (engine.restart: resolve_train.merge_rest); a conflict joins with its
resolve order, red light checks with their fix order, a riding car's newer head as its update, a hand merge as a car;
`tollman.py cars --json` says where every hitched wagon stands. Whole rounds on engine_farm.py's farm."""
# enforces .adr/tollman.md and .adr/hitch-is-forever.md

import json
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import train_state
import trains
from engine_farm import Farm, out
from test_farmer import git

GREEN = {"state": "green", "lines": []}
RUN = "https://github.com/x/runs/9"


class Open(Farm):
    """Train 07+09 lands, goes red and stands; the wagons hitched after it join it before its next push."""

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
        self.assertEqual(self.train()["state"], "red")

    def cars(self):
        return [c["field"] for c in self.train()["cars"]]

    def joined(self):
        return [e for e in train_state.lines(str(self.main)) if e["kind"] == "joined"]

    def test_a_wagon_hitched_while_the_train_is_red_joins_and_its_next_start_merges_it(self):
        """E3, E4: red, then retry: the join is recorded at once (the carrier untouched), merged by the restart."""
        eleven = self.crop("11", {"eleven.txt": "11"}, plan="0611-eleven")
        head = out(self.cw, "rev-parse", "HEAD")
        self.round()
        self.assertEqual((self.last, self.cars(), self.train()["state"]), ([("join", "run", "-")], ["07", "09", "11"],
                                                                          "red"))
        line = self.joined()[-1]
        self.assertEqual((line["merged"], line["cars"][0]["head"], out(self.cw, "rev-parse", "HEAD")),
                         (False, eleven["ready"]["head"], head), "recorded, the carrier as it was")
        self.assertIn("11", {c["field"] for c in self.gate.of(self.carrier())["train"]["cars"]}, "the queue's mark")
        self.round()
        self.assertEqual(len(self.joined()), 1, "once")
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 0)
        self.round()
        self.assertEqual((self.train()["state"], self.cars()), ("landing", ["07", "09", "11"]))
        self.assertEqual(out(self.cw, "merge-base", "--is-ancestor", eleven["ready"]["head"], "HEAD"), "")
        self.assertEqual(self.gate.calls[-1][:7], ["worktree", "queue", "train", self.carrier(), "07", "09", "11"])

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

    def test_a_conflicting_joiner_rides_and_its_start_waits_for_its_resolve(self):
        """E5 outside a landing: never kept out; the start merges it and waits `resolving` with its resolve order."""
        self.crop("11", {"nine.txt": "eleven"})  # conflicts with car 09
        self.round()
        self.assertEqual((self.cars(), self.joined()[-1]["cars"][0].get("conflict")), (["07", "09", "11"], ["nine.txt"]))
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 0)
        self.round()
        t = self.train()
        self.assertEqual((t["state"], t["resolve"]["field"], t["resolve"]["id"]), ("resolving", "11", "11-resolve-1"))
        self.panes["11"] = "%11"
        self.round()
        self.assertIn(("resolve-order", "send", "11"), self.last, "its foreman gets the resolve order")

    def test_a_joiner_with_red_light_checks_gets_its_fix_order_in_the_red_train(self):
        """E5: a red proof joins with `proof_red`; the round orders its fix in the train (proof_orders.py)."""
        self.crop("11", {"eleven.txt": "11"})
        with mock.patch.object(trains, "PROVE", lambda main, field, head, barn: {
                "state": "red", "lines": ["names: eleven.txt"]} if field.endswith("/11") else GREEN):
            self.round()
            self.assertEqual(self.train()["cars"][-1]["proof_red"], ["names: eleven.txt"])
            self.round()
        order = [e for e in train_state.lines(str(self.main)) if e["kind"] == "order"][-1]
        self.assertEqual((order["field"], order["jobs"], self.train()["state"]), ("11", ["python-lint"], "fixing"))

    def test_a_riding_car_s_newer_head_joins_as_its_update(self):
        """E10: 09 hitched again on a newer head while its train is red: its car's place, merged by the next start."""
        path = self.fields["09"]
        (path / "nine.txt").write_text("9, newer")
        git(path, "commit", "-qam", "nine, newer")
        git(path, "push", "-q", "origin", "HEAD")
        new = out(path, "rev-parse", "HEAD")
        self.gate.of("09")["ready"] = dict(self.gate.of("09")["ready"], head=new)
        self.round()
        self.assertEqual((self.cars(), self.train()["cars"][1]["head"]), (["07", "09"], new))
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 0)
        self.round()
        self.assertEqual((self.train()["state"], out(self.cw, "merge-base", "--is-ancestor", new, "HEAD")),
                         ("landing", ""))

    def test_a_hand_merge_into_the_carrier_is_recorded_as_a_car(self):
        """E8: the tollman merged 11 into the carrier by hand: the next round records it (`carried`, merged)."""
        eleven = self.crop("11", {"eleven.txt": "11"})
        git(self.cw, "merge", "-q", "--no-ff", "-m", "by hand", eleven["ready"]["head"])
        with mock.patch.object(trains, "PROVE", side_effect=AssertionError("a carried head is never proven again")):
            self.round()
        line = self.joined()[-1]
        self.assertEqual((self.cars(), line["merged"], line["cars"][0].get("carried")), (["07", "09", "11"], True, True))

    def test_join_by_hand_records_the_car_or_says_why_it_waits(self):
        """D8a: `tollman.py join <field>` is the hand's way in; a servant's field is refused with its reason."""
        self.crop("11", {"eleven.txt": "11"})
        servant = self.crop("12", {"twelve.txt": "12"})
        (self.fields["12"] / "plans").mkdir(exist_ok=True)
        (self.fields["12"] / "plans/LEAD").write_text("13\n")
        code, text = self.call("join", "12")
        self.assertEqual(code, 1, text)
        self.assertIn("a servant's field (plans/LEAD) never rides", text)
        code, text = self.call("join", "11")
        self.assertEqual(code, 0, text)
        self.assertIn("field 11 (11, ", text)
        self.assertEqual((self.cars(), self.joined()[-1]["merged"]), (["07", "09", "11"], False))
        self.assertTrue(servant["ready"], "the servant stays hitched")

    def test_cars_says_where_every_hitched_wagon_stands(self):
        """D8b: the cars and every hitched wagon from the queue, the train state and the train's branch."""
        eleven = self.crop("11", {"eleven.txt": "11"})
        self.crop("12", {"twelve.txt": "12"})
        (self.fields["12"] / "plans").mkdir(exist_ok=True)
        (self.fields["12"] / "plans/LEAD").write_text("13\n")
        git(self.cw, "merge", "-q", "--no-ff", "-m", "by hand", eleven["ready"]["head"])
        code, text = self.call("cars", "--json")
        self.assertEqual(code, 0, text)
        d = json.loads(text)
        self.assertEqual((d["schema"], d["train"]["state"], d["train"]["open"], d["train"]["pushed"]),
                         (1, "red", True, False))
        self.assertEqual([(c["field"], c["in_branch"]) for c in d["cars"]], [("07", True), ("09", True)])
        where = {h["field"]: (h["where"], h.get("reason")) for h in d["hitched"]}
        self.assertEqual(where, {"07": ("car", None), "09": ("car", None), "11": ("in-branch", None),
                                 "12": ("waits", "servant")})
        git(self.cw, "reset", "-q", "--hard", "HEAD^")
        self.assertEqual({h["field"]: h["where"] for h in json.loads(self.call("cars", "--json")[1])["hitched"]}["11"],
                         "joins")
        self.round()
        d = json.loads(self.call("cars", "--json")[1])
        self.assertEqual([(c["field"], c["in_branch"]) for c in d["cars"]][-1], ("11", False))
        self.assertEqual({h["field"]: h["where"] for h in d["hitched"]}["11"], "car")
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
