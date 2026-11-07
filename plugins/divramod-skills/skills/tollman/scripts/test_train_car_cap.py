"""Hal2 plan 0722 (tollman learning L270): the user's standing `max-cars <n>` caps every train, a join to a standing,
never started train included (D2: its cars count, a full train takes no new field, a riding car's newer head keeps
its place, an alone car is still owed the very next train, D4), and lowers the round's minimum to n (D3), so with
`minimum 999` and `max-cars 3` 16 hitched wagons ride 3 at a time in queue order. Whole rounds on engine_farm.py's
farm; a never started train as test_engine's form-died one."""
# enforces .adr/tollman.md and .adr/hitch-is-forever.md

import json
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import standing
import train_cars
import train_state
import trains
from engine_farm import OWN, Farm, out
from test_farmer import git

GREEN = {"state": "green", "lines": []}
WORDS = "the user, 2026-11-06: tollman should start building trains with 3 cars"
SIXTEEN = [f"{n:02}" for n in range(10, 26)]


class Cap(Farm):
    def setUp(self):
        super().setUp()
        proven = mock.patch.object(trains, "PROVE", lambda *a: GREEN)
        proven.start()
        self.addCleanup(proven.stop)
        self.top = str(self.main)

    def cap(self, n=3):
        standing.add(self.top, "max-cars", n, WORDS)

    def crops(self, names):
        for f in names:
            self.crop(f, {f"f{f}.txt": f})

    def cars(self):
        return [c["field"] for c in self.train()["cars"]]

    def where(self):
        return {h["field"]: (h["where"], h.get("reason")) for h in train_cars.of(self.top)["hitched"]}

    def formed(self, fields):
        """A train formed of `fields` and never started (its form's process gone, only its first car merged)."""
        base = out(self.wm, "rev-parse", "HEAD")
        cars = [{"field": f, "branch": f, "head": self.gate.of(f)["ready"]["head"], "plan": ""} for f in fields]
        train_state.append(self.top, "formed", OWN, train="+".join(fields) + "@x", cars=cars, base=base, number=1)
        git(self.wm, "merge", "-q", "--no-ff", "-m", f"Merge branch '{fields[0]}' into {self.branch()}",
            cars[0]["head"])

    def joined(self):
        return [c["field"] for e in train_state.lines(self.top) if e["kind"] == "joined" for c in e.get("cars", [])]


class L270(Cap):
    """The replay: standing `minimum 999` (the tollman's workaround) and `max-cars 3`, 16 wagons hitched."""

    def setUp(self):
        super().setUp()
        standing.add(self.top, "minimum", 999, "the user, 2026-11-06: no 10-car trains")
        self.cap()
        self.crops(SIXTEEN)

    def test_the_round_forms_three_cars_and_the_next_round_three_more(self):
        self.assertEqual(trains.minimum(self.top), 3, "D3: the minimum is at most the cap")
        where = self.where()
        self.assertEqual([where[f] for f in SIXTEEN], [("forms", None)] * 3 + [("waits", "max-cars")] * 13,
                         "the field table agrees with the round")
        d = json.loads(self.call("train", "--dry-run", "--json")[1])
        self.assertEqual(([c["field"] for c in d["cars"]], {w["reason"] for w in d["waiting"]}),
                         (SIXTEEN[:3], {"max-cars"}))
        self.round()
        self.assertEqual(self.cars(), SIXTEEN[:3], "3 cars in queue order, no wait for 999 hitched")
        self.assertTrue(all(self.gate.of(f)["ready"] for f in SIXTEEN[3:]), "the other 13 stay hitched")
        rest = [t for t in self.gate.tickets if t["slot"] in SIXTEEN[3:]]
        self.ends({"status": "landed", "commit": "c0ffee"}, land=True)
        self.gate.tickets = rest  # the landing took only its cars' tickets
        for _ in range(2):
            self.round()
            if self.train():
                break
        self.assertEqual((self.cars(), self.train()["number"]), (SIXTEEN[3:6], 2), "the next 3, in queue order")

    def test_a_join_to_a_full_standing_train_takes_none(self):
        self.formed(SIXTEEN[:3])
        self.round()
        self.assertEqual((self.joined(), self.cars()), ([], SIXTEEN[:3]), "a full train takes no joiner")
        self.assertEqual(self.gate.calls[-1][:6], ["worktree", "queue", "train", self.carrier(), *SIXTEEN[:2]])
        self.assertEqual(self.gate.calls[-1][6], SIXTEEN[2])
        self.assertTrue(all(self.gate.of(f)["ready"] for f in SIXTEEN[3:]), "never unhitched")


class Join(Cap):
    """A join counts the standing train's cars (D2); without the cap it takes every wagon as before."""

    def test_a_two_car_train_takes_one_joiner_in_queue_order(self):
        self.cap()
        self.crops(["07", "09", "11", "12"])
        self.formed(["07", "09"])
        self.round()
        self.assertEqual((self.joined(), self.cars()), (["11"], ["07", "09", "11"]))
        self.assertEqual(self.where()["12"][0], "next", "12 rides a later train, hitched")
        self.assertTrue(self.gate.of("12")["ready"])

    def test_the_field_table_names_the_cap_for_an_open_train(self):
        self.cap()
        self.crops(["07", "09", "11", "12"])
        self.formed(["07", "09"])
        self.assertEqual({f: self.where()[f] for f in ("11", "12")}, {"11": ("joins", None), "12": ("waits", "max-cars")})

    def test_a_riding_car_s_newer_head_still_joins_a_full_train(self):
        """E10 under the cap: the newer head takes its own car's place, a new field does not join."""
        self.cap()
        self.crops(["07", "09", "11"])
        self.formed(["07", "09", "11"])
        self.crop("12", {"f12.txt": "12"})
        path = self.fields["09"]
        (path / "nine.txt").write_text("9, newer")
        git(path, "add", "nine.txt")
        git(path, "commit", "-qm", "nine, newer")
        git(path, "push", "-q", "origin", "HEAD")
        new = out(path, "rev-parse", "HEAD")
        t = self.gate.tickets.pop(next(i for i, t in enumerate(self.gate.tickets) if t["slot"] == "09"))
        self.gate.tickets.append(dict(t, ready=dict(t["ready"], head=new)))  # hitched again, after 12
        self.round()
        self.assertEqual((self.joined(), self.cars(), self.train()["cars"][1]["head"]), (["09"], ["07", "09", "11"], new))

    def test_an_alone_car_is_still_owed_the_very_next_train_by_a_full_one(self):
        """D4 (plan 0610 D15): a full train takes no joiner, an alone car hitched meanwhile is owed the next train."""
        self.cap(2)
        self.crops(["07", "09"])
        self.formed(["07", "09"])
        self.crop("13", {".github/workflows/merge-to-main.yml": "on: push\n"})
        self.round()
        self.assertEqual(trains.owed(train_state.lines(self.top)), ["13"])
        self.assertEqual((self.joined(), self.cars()), ([], ["07", "09"]))

    def test_without_the_cap_every_wagon_joins_and_the_minimum_is_the_order_s(self):
        standing.add(self.top, "minimum", 999, "the user: big trains")
        self.assertEqual(trains.minimum(self.top), 999)
        self.crops(["07", "09", "11", "12"])
        self.formed(["07", "09"])
        self.round()
        self.assertEqual((self.joined(), self.cars()), (["11", "12"], ["07", "09", "11", "12"]))


if __name__ == "__main__":
    unittest.main()
