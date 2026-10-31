"""Tollman learning L95: a reserved place holds only the wagons behind it in queue order. The user ordered 16 in ahead
of 17's reserved place (queue order 16 17); 16 was hitched, 17 not ready, and the trains still waited behind 17.
hal2-git's carrier takes its first car's place (queue/train/front_tests.rs), so the train rides ahead of 17."""
# enforces .adr/tollman.md

import unittest

import test_trains
import trains

RESERVED = {"by": "the user", "since": test_trains.AT}


def place(field, pos, **kw):
    """A place the user's order reserved for `field`, not ready, no process."""
    return {"slot": field, "position": pos, "state": "waiting", "branch": field, "worktree": f"/w/{field}",
            "seq": pos + 1, "pid": 0, "ready": None, "train": None, "rides_with": None, "reserved": RESERVED, **kw}


class Held(test_trains.Crops):
    def test_a_reservation_behind_the_first_wagon_holds_only_the_wagons_behind_it(self):
        q = self.queue(**{"16": {"sixteen.txt": "16"}, "17x": {"x.txt": "x"}, "18": {"eighteen.txt": "18"}})
        tickets = [q[0], place("17", 1), q[2]]
        self.assertIsNone(trains.held_for(tickets, "tollman-hal2"), "16 stands ahead of 17's place")
        d = self.draft(tickets)
        self.assertEqual(self.cars(d), ["16"])
        self.assertEqual([w["field"] for w in d["waiting"]], ["18"])
        self.assertIn("the place reserved for field 17", d["waiting"][0]["why"])

    def test_a_reservation_ahead_of_every_wagon_holds_the_train(self):
        q = self.queue(**{"16": {"sixteen.txt": "16"}})
        tickets = [place("17", 0), dict(q[0], position=1)]
        self.assertEqual(trains.held_for(tickets, "tollman-hal2"), "17")
        d = self.draft(tickets)
        self.assertEqual((self.cars(d), [w["field"] for w in d["waiting"]]), ([], ["16"]))

    def test_a_reserved_place_with_its_own_landing_or_ready_mark_holds_nothing(self):
        q = self.queue(**{"16": {"sixteen.txt": "16"}})
        for kw in ({"pid": 4711}, {"state": "held"}, {"slot": "tollman-hal2"}):
            tickets = [place("17", 0, **kw), dict(q[0], position=1)]
            self.assertIsNone(trains.held_for(tickets, "tollman-hal2"), kw)
            self.assertEqual(self.cars(self.draft(tickets)), ["16"], kw)


if __name__ == "__main__":
    unittest.main()
