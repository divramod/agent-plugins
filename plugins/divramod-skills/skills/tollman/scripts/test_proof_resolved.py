"""L258 (hal2 plan 0695 row 22): a car whose resolve is on the carrier is proved on the carrier's head, never on its
old hitched head: no fix order for lines the resolve changed already."""
# enforces .adr/tollman.md

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import proof_orders
import proof_resolved

OLD = "names: plans/x/n.md:1: slot — use worktree"
HITCHED = "5ab4457ee0" + "0" * 30


class Resolved(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.carrier = self.dir.name
        for argv in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                                      "-m", "x"]):
            subprocess.run(["git", *argv], cwd=self.carrier, check=True, capture_output=True)
        self.head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.carrier, text=True, capture_output=True,
                                   check=True).stdout.strip()
        self.train = {"train": "56-5", "base": "b" * 40, "worktree": self.carrier, "state": "red",
                      "cars": [{"field": "19", "head": HITCHED, "proof_red": [OLD]}]}
        self.rows = [{"kind": "resolved", "train": "56-5", "field": "19"}]
        self.seen = []

    def prove(self, state, lines=()):
        def verdict(main, field, head, barn):
            self.seen.append((field, head, barn))
            return {"state": state, "lines": list(lines)}
        return verdict

    def test_a_resolved_car_is_proved_on_the_carrier_head_and_green_orders_nothing(self):
        t = proof_resolved.live("/f/tollman", "/f/hal2", self.train, self.rows, self.prove("green"))
        self.assertEqual(self.seen, [(self.carrier, self.head, "b" * 40)], "the carrier's head, never 5ab4457ee0")
        self.assertNotIn("proof_red", t["cars"][0])
        self.assertEqual(self.train["cars"][0]["head"], HITCHED, "the hitched head stays")
        with mock.patch.object(proof_resolved.proof, "verdict", self.prove("green")):
            acts = proof_orders.actions("/f/tollman", "/f/hal2", self.train, self.rows)
        self.assertEqual(acts, [], "no fix order for a red the resolve already fixed")

    def test_a_still_red_resolved_car_keeps_the_carriers_lines(self):
        t = proof_resolved.live("/f/tollman", "/f/hal2", self.train, self.rows, self.prove("red", ["names: new"]))
        self.assertEqual(t["cars"][0]["proof_red"], ["names: new"])

    def test_an_unresolved_car_is_not_proved_again(self):
        t = proof_resolved.live("/f/tollman", "/f/hal2", self.train, [], self.prove("green"))
        self.assertEqual((self.seen, t["cars"][0]["proof_red"]), ([], [OLD]))

    def test_the_red_line_waits_for_the_carrier_proof(self):
        with mock.patch.object(proof_resolved.proof, "verdict", self.prove("green")), \
                mock.patch.object(proof_orders.train_state, "lines", return_value=self.rows):
            self.assertEqual(proof_orders.red_line("/f/hal2", "train-56-5", self.train, top="/f/tollman"), "")


if __name__ == "__main__":
    unittest.main()
