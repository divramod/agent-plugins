"""Hal2 plan 0375 D8, D19: which wagons ride (kinds.py). A wagon's kind is its entry's effective mode (plan 0365 D5).
Awake, a train takes only adjacent production wagons: a hitched smuggle entry is no car (its own /mtm smuggles it, the
farmer's lead tells it); a smuggle entry behind a wagon that may ride cuts the train, the production wagons after it
wait for the next one. The queue is engine_farm's Gate (a fake hal2-cli-git whose tickets carry `mode` and
`effective_mode`), git a temporary repository: no real queue or session."""

import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import kinds
from engine_farm import Farm

OWN = "tollman-hal2"
SMUGGLE = {"mode": "smuggle", "by": "user", "at": "2026-10-18T09:00:00Z"}


def t(slot, n, mode=None, ready=True, **kw):
    return {"slot": slot, "position": n, "state": "waiting", **({"effective_mode": mode} if mode else {}),
            "ready": {"head": slot * 20, "at": "x"} if ready else None, **kw}


class Split(unittest.TestCase):
    def test_the_kind_is_the_entrys_effective_mode(self):
        self.assertEqual((kinds.of({}, None), kinds.of({"effective_mode": "smuggle"}, None),
                          kinds.of({"mode": "smuggle"}, None), kinds.of({}, SMUGGLE),
                          kinds.of({"effective_mode": "production"}, SMUGGLE)),
                         ("production", "smuggle", "smuggle", "smuggle", "production"))

    def test_production_wagons_ride_a_hitched_smuggler_waits_and_cuts(self):
        rides, waiting = kinds.split([t("07", 1), t("08", 2, "smuggle"), t("09", 3)], OWN)
        self.assertEqual([r["slot"] for r in rides], ["07"])
        self.assertEqual([w["field"] for w in waiting], ["08", "09"])
        self.assertIn("smuggles itself", waiting[0]["why"])
        self.assertIn("the smuggler 08 passes alone", waiting[1]["why"])

    def test_a_smuggler_in_front_cuts_nothing(self):
        rides, waiting = kinds.split([t("05", 1, "smuggle", ready=False), t("07", 2), t("09", 3)], OWN)
        self.assertEqual(([r["slot"] for r in rides], waiting), (["07", "09"], []))

    def test_the_head_and_own_ticket_neither_ride_nor_cut(self):
        tickets = [t("02", 0, "smuggle", state="landing"), t(OWN, 1, ready=False), t("07", 2),
                   t("05", 3, "smuggle", ready=False), t("09", 4)]
        rides, waiting = kinds.split(tickets, OWN)
        self.assertEqual([r["slot"] for r in rides], ["02", OWN, "07"])
        self.assertEqual([w["field"] for w in waiting], ["09"], "cut by the waiting smuggler 05")

    def test_the_queues_smuggle_mode_is_every_entrys_default(self):
        rides, waiting = kinds.split([t("07", 1, "production"), t("08", 2), t("09", 3, "production")], OWN, SMUGGLE)
        self.assertEqual(([r["slot"] for r in rides], [w["field"] for w in waiting]), (["07"], ["08", "09"]))


class Trains(Farm):
    def test_a_train_forms_only_of_adjacent_production_wagons(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("08", {"eight.txt": "8"})["effective_mode"] = "smuggle"
        self.crop("09", {"nine.txt": "9"})
        self.panes = {"08": "%8"}
        self.round()
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07"], "09 is not adjacent: the smuggler cuts")
        self.assertTrue(self.gate.of("08")["ready"], "its hitch stays for its own /mtm")
        self.assertEqual(self.typed, [], "the farmer's lead tells the smuggler, not the tollman")

    def test_without_smugglers_the_production_wagons_ride_together(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})["effective_mode"] = "production"
        self.round()
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07", "09"])


if __name__ == "__main__":
    unittest.main()
