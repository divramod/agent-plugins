"""Hal2 plan 0611 step 5 (design.md §3, D13): the user's standing orders are records the train code reads. An open
`minimum` order changes when a train forms and an open `hold` keeps it from forming; a revoked one is ignored. Words
are required to set and to end one; a second order of a rule revokes the first. Whole rounds on engine_farm.py's
farm with the minimum at 3 (as test_engine.Minimum)."""

import json
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import hold
import role_records
import standing
import train_cars
import trains
from engine_farm import Farm

WORDS = "the user, 2026-11-05: at least two fields per train"


class Orders(Farm):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(trains, "MIN_HITCHED", 3)
        p.start()
        self.addCleanup(p.stop)
        self.top = str(self.main)

    def two(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})

    def open_ids(self):
        return [r["id"] for r in standing.opened(self.top)]

    def test_an_open_minimum_order_applies_and_a_revoked_one_does_not(self):
        self.assertEqual(trains.minimum(self.top), 3, "no order: the code's default")
        rec = standing.add(self.top, "minimum", 2, WORDS)
        self.assertEqual((rec["by"], rec["words"], standing.value(self.top, "minimum")), ("user", WORDS, 2))
        self.assertEqual(trains.minimum(self.top), 2)
        self.two()
        self.round()
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07", "09"], "two hitched are enough now")
        self.assertTrue(standing.revoke(self.top, rec["id"], "the user: back to the default"))
        self.assertEqual((standing.value(self.top, "minimum"), trains.minimum(self.top)), (None, 3))

    def test_a_revoked_minimum_order_leaves_two_fields_waiting(self):
        rec = standing.add(self.top, "minimum", 2, WORDS)
        standing.revoke(self.top, rec["id"], "the user: no minimum of mine")
        self.two()
        self.round()
        self.assertIsNone(self.train(), "the default 3 applies again")
        d = train_cars.of(self.top)
        self.assertEqual([h["reason"] for h in d["hitched"]], ["minimum", "minimum"])
        standing.add(self.top, "minimum", 2, WORDS)
        self.assertEqual([h["where"] for h in train_cars.of(self.top)["hitched"]], ["forms", "forms"])

    def test_an_open_hold_order_is_read_by_hold_and_a_revoked_one_is_not(self):
        self.assertIsNone(hold.of(self.top))
        code, text = self.call("hold", "--by", "user", "--words", WORDS, "--why", "CI rebuild")
        self.assertEqual(code, 0, text)
        held = hold.of(self.top)
        self.assertEqual((held["why"], held["words"], held["by"]), ("CI rebuild", WORDS, "user"))
        self.assertEqual([r["rule"] for r in standing.opened(self.top)], ["hold"])
        self.assertIn("held: CI rebuild", self.call("status")[1])
        self.assertEqual(self.call("unhold")[0], 1, "an unhold without the user's words is refused")
        self.assertIsNotNone(hold.of(self.top))
        code, _ = self.call("unhold", "--by", "user", "--words", "the user: let them form")
        self.assertEqual((code, hold.of(self.top), self.open_ids()), (0, None, []))

    def test_a_legacy_hold_json_is_read_until_unhold_removes_it(self):
        hold.path(self.top).write_text(json.dumps({"why": "old", "at": "2026-11-01T00:00:00Z", "by": "user", "words": "w"}))
        self.assertEqual(hold.of(self.top)["why"], "old")
        self.call("unhold", "--by", "user", "--words", "the user: done")
        self.assertEqual((hold.of(self.top), hold.path(self.top).exists()), (None, False))

    def test_a_standing_order_needs_the_user_s_words_and_a_known_rule(self):
        for args in (("minimum", "2"), ("minimum", "x"), ("nonsense", "")):
            with self.assertRaises(ValueError):
                standing.add(self.top, args[0], args[1], "" if args[1] == "2" else WORDS)
        self.assertEqual(self.open_ids(), [])
        code, text = self.call("standing", "add", "minimum", "--value", "2", "--words", WORDS)
        self.assertEqual(code, 1, text)
        self.assertEqual(self.call("standing", "add", "minimum", "--value", "2", "--by", "user", "--words", WORDS)[0], 0)
        self.assertEqual(self.call("standing", "revoke", "R1", "--by", "user")[0], 1, "a revoke needs words too")
        self.assertEqual(self.open_ids(), ["R1"])

    def test_a_second_order_of_a_rule_revokes_the_first_and_no_code_closes_one(self):
        first = standing.add(self.top, "minimum", 2, WORDS)
        second = standing.add(self.top, "minimum", 5, WORDS)
        self.assertEqual((self.open_ids(), standing.value(self.top, "minimum")), ([second["id"]], 5))
        rows = role_records.fold(role_records.lines(self.top, "tollman"))
        self.assertEqual((rows[first["id"]]["closed"], rows[first["id"]]["how"]), (True, "user"))
        self.assertEqual(role_records.sweep(self.top, "tollman"), [], "the sweep has no closer for a standing order")
        self.assertEqual(self.open_ids(), [second["id"]])
        standing.add(self.top, "every-wagon-rides", None, WORDS)
        code, text = self.call("standing", "list")
        self.assertEqual(code, 0)
        self.assertIn("every-wagon-rides", text)

class MaxCars(Orders):
    """Plan 0695 D62: the standing `max-cars <n>` caps a train; the rest stay hitched for a later train."""

    def three(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        self.crop("14", {"f14.txt": "14"})

    def test_a_train_takes_at_most_n_cars_in_queue_order_and_the_rest_stay_hitched(self):
        standing.add(self.top, "max-cars", 2, WORDS)
        self.assertEqual(standing.value(self.top, "max-cars"), 2)
        self.three()
        self.round()
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07", "09"], "the first two ride")
        rows = {h["field"]: h for h in train_cars.of(self.top)["hitched"]}
        self.assertEqual(rows["14"]["where"], "next", "the third rides the next train, still hitched")
        self.assertTrue(next(x for x in self.gate.tickets if x["slot"] == "14")["ready"], "never unhitched")

    def test_a_revoked_max_cars_takes_every_wagon_again_and_the_value_must_be_a_number(self):
        with self.assertRaises(ValueError):
            standing.add(self.top, "max-cars", "x", WORDS)
        rec = standing.add(self.top, "max-cars", 2, WORDS)
        self.assertEqual(self.call("standing", "revoke", rec["id"], "--by", "user", "--words", "the user: no cap")[0], 0)
        self.assertEqual((standing.value(self.top, "max-cars"), self.open_ids()), (None, []))
        self.three()
        self.round()
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07", "09", "14"])

    def test_the_cap_is_set_by_the_command_and_a_second_one_replaces_the_first(self):
        code, text = self.call("standing", "add", "max-cars", "--value", "3", "--by", "user", "--words", WORDS)
        self.assertEqual(code, 0, text)
        standing.add(self.top, "max-cars", 1, WORDS)
        self.assertEqual(standing.value(self.top, "max-cars"), 1)
        self.assertEqual(len(self.open_ids()), 1)


if __name__ == "__main__":
    unittest.main()
