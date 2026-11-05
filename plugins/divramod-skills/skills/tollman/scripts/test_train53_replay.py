"""Hal2 plan 0620 step 3 (tollman learning L254, train 53): the restart after a proof_red restart and a fix. Train
07+09 lands once and goes red; car 83 joins with red light checks, the session's `retry` restarts the train, that
restart ends on `proof_red` (no landing, `starts` unchanged), 83 is ordered and fixed, and the next round restarts
under a NEW key (it stood on the used `retry:<train>:<starts>` before); car 74, joining the then retrying train with
other red findings, gets its own fix order. Whole rounds on engine_farm.py's farm."""
# enforces .adr/tollman.md

import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import train_state
import trains
from engine_farm import Farm, out

GREEN = {"state": "green", "lines": []}
RUN = "https://github.com/x/runs/53"


def prove(main, field, head, barn):
    """Cars 83 and 74 have red light checks, each its own finding (so neither is a twin of the other)."""
    name = field.rsplit("/", 1)[-1]
    return {"state": "red", "lines": [f"names: {name}.txt"]} if name in ("83", "74") else GREEN


class Train53(Farm):
    def setUp(self):
        super().setUp()
        proven = mock.patch.object(trains, "PROVE", prove)
        proven.start()
        self.addCleanup(proven.stop)
        self.crop("07", {"seven.txt": "7"}, plan="0294-tollman-role")
        self.crop("09", {"nine.txt": "9"})
        self.round()
        self.ends({"status": "gate_failed", "run": RUN, "red": [{"name": "linux / rust-test"}]})
        self.gate.of(self.carrier()).update(state="held", train=None, hold={"reason": "failed"})
        self.round()
        self.assertEqual((self.train()["state"], self.train()["starts"]), ("red", 1))

    def kinds(self, kind):
        return [e for e in train_state.lines(str(self.main)) if e["kind"] == kind]

    def fixed(self, field):
        t = self.train()
        order = [o for o in self.kinds("order") if o["field"] == field][-1]
        train_state.append(str(self.main), "fixed", self.carrier(), train=t["train"], field=field, id=order["id"],
                           sha="f" * 40, commit=out(self.cw, "rev-parse", "HEAD"))

    def test_a_train_fixed_after_a_proof_red_restart_restarts_on_the_next_round(self):
        """L254: `retry`, the join and the restart in one round; the restart ends proof_red (the key used up, `starts`
        still 1), 83 is ordered and fixed, and the next round restarts the train under a new key."""
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 0)
        self.crop("83", {"x83.txt": "83"})
        self.round()
        t = self.train()
        self.assertEqual((self.last, [c["field"] for c in t["cars"]], t["state"], t["status"], t["starts"]),
                         ([("join", "run", "-"), ("restart", "run", "-")], ["07", "09", "83"], "red", "proof_red", 1),
                         "proof_red: no landing, no start")
        self.assertEqual(len(self.spawned), 1)
        self.round()
        self.assertEqual((self.last, self.train()["state"]), ([("proof-order", "run", "83")], "fixing"))
        self.fixed("83")
        t = self.train()
        self.assertEqual((t["state"], t["starts"]), ("retry", 1))
        self.round()
        t = self.train()
        self.assertEqual((self.last, t["state"], t["starts"], len(self.spawned)),
                         ([("restart", "run", "-")], "landing", 2, 2),
                         "L254: the fixed train restarts on the next round (the used key blocked it for 20 minutes)")

    def test_a_car_that_joined_red_before_the_train_turned_retry_is_ordered_not_restarted(self):
        """L254, car 74: joined with red light checks, the train put to `retry` before its order: the round orders it
        (proof_orders.pending) and starts nothing past it."""
        self.crop("74", {"y74.txt": "74"})
        self.round()
        self.assertEqual(([c["field"] for c in self.train()["cars"]], self.train()["state"]), (["07", "09", "74"], "red"))
        self.assertEqual(self.kinds("order"), [], "no order yet")
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 0)
        self.round()
        t = self.train()
        self.assertEqual((self.last, t["state"], t["starts"], len(self.spawned)),
                         ([("proof-order", "run", "74")], "fixing", 1, 1), "74 is ordered, no restart")
        self.assertEqual([o["field"] for o in self.kinds("order")], ["74"])


if __name__ == "__main__":
    unittest.main()
