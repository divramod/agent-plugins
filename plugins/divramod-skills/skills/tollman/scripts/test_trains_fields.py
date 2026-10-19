"""Hal2 plan 0383 step 16 (D16): a foreman works in any field 00-99, so its wagon from field 30 rides a train; only a
field holding `plans/LEAD` (a servant's, whatever its number) never hitches. Real git (test_trains.Crops)."""
# enforces .adr/tollman.md

import unittest

import test_trains as tt
import trains


class Fields(tt.Crops):
    def test_a_foremans_wagon_from_field_30_and_from_field_99_rides(self):
        q = self.queue(**{"07": {"seven.rs": "7\n"}, "30": {"thirty.rs": "30\n"}, "99": {"ninety.rs": "99\n"}})
        d = self.draft(q)
        self.assertEqual((self.cars(d), d["unhitched"]), (["07", "30", "99"], []))

    def test_a_field_holding_plans_lead_never_rides_whatever_its_number(self):
        q = self.queue(**{"07": {"seven.rs": "7\n"}, "05": {"five.rs": "5\n"}, "30": {"thirty.rs": "30\n"}})
        q[1]["worktree"] = self.servant_field()
        d = self.draft(q)
        self.assertEqual(self.cars(d), ["07", "30"])
        self.assertEqual([(u["field"], u["tell"]) for u in d["unhitched"]], [("05", "servant")])

    def test_servant_reads_the_marker_not_the_number(self):
        self.assertTrue(trains.servant(self.servant_field()))
        self.assertFalse(trains.servant(self.d) or trains.servant(None) or trains.servant(""))


if __name__ == "__main__":
    unittest.main()
