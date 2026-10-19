"""Hal2 plan 0383 step 7 (D7): `tollman.py hold`/`unhold`. While held, no train forms, restarts or lands: not the
round's, not the chain's, not the green merge job's next train; the watch goes on and a landing that runs is never
cut. Unhold lets the trains form again. Whole passes and rounds on test_next_train's farm; gh is gh_fake.py's."""
# enforces .adr/deterministic-first.md, .adr/merge-queue-policy.md and .adr/tollman.md

import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import hold
import trains
from test_next_train import MERGE, Trains
from gh_fake import job


def held_kinds(actions):
    return [a["kind"] for a in actions]


class Verbs(Trains):
    def test_hold_and_unhold_write_and_remove_the_file_and_status_shows_it(self):
        self.assertIsNone(hold.of(str(self.main)))
        code, text = self.call("hold", "--why", "CI is being rebuilt")
        self.assertEqual(code, 0)
        self.assertIn("held: CI is being rebuilt", text)
        self.assertEqual(hold.of(str(self.main))["why"], "CI is being rebuilt")
        self.assertIn("held: CI is being rebuilt", self.call("status")[1])
        self.assertEqual(self.call("status", "--json")[0], 0)
        code, text = self.call("unhold")
        self.assertEqual((code, hold.of(str(self.main))), (0, None))
        self.assertNotIn("held:", self.call("status")[1])
        self.assertEqual(self.call("unhold")[1], "no hold was set\n")


class Held(Trains):
    def test_a_running_landing_goes_on_and_is_watched_while_held(self):
        self.call("hold", "--why", "pause the trains")
        self.crop("03", {"three.txt": "3"}, plan="0382-three")
        self.panes["03"] = "%3"
        self.gh.jobs["720"] = [job("d1-01-rust-test", "success"), MERGE]
        self.assertIn("merge job green", self.minute(), "the watch goes on")
        self.round()
        self.assertEqual((self.train()["train"], self.train()["state"], len(self.spawned)),
                         (self.a["train"], "landing", 1), "its process runs: never cut, nothing else started")
        self.assertNotIn("form", [k for k, _, _ in self.last])

    def test_a_held_green_merge_forms_no_next_train_and_unhold_resumes(self):
        self.crop("03", {"three.txt": "3"}, plan="0382-three")
        self.panes["03"] = "%3"
        self.call("hold", "--why", "no more trains tonight")
        self.merged()  # the merge job green, the landing's process ended
        self.assertEqual(self.minute(), "", "no chain: nothing to form behind the green merge")
        self.round()  # the round settles the landed train, forms nothing
        self.assertEqual(self.train(), None)
        self.assertEqual(len(self.spawned), 1)
        self.assertNotIn("formed", [k for k, _ in self.state()][[k for k, _ in self.state()].index("landed"):])
        self.assertTrue(any(a["kind"] == "held" for a in self.round()["planned"]), "one held line each round")
        self.assertEqual(self.call("chain")[0], 0)
        self.assertEqual((self.train(), len(self.spawned)), (None, 1), "the chain forms nothing either")
        self.call("unhold")
        self.round()
        t = self.train()
        self.assertEqual(([c["field"] for c in t["cars"]], t["state"], len(self.spawned)), (["03"], "landing", 2))


class Plan(unittest.TestCase):
    """trains.plan on data: the hold stops forming and restarting, not the watch of a landing."""
    TOP, MAIN = "/no/such/farm/tollman-hal2", "/no/such/farm"
    HELD = {"why": "x", "at": "2026-10-19T10:00:00Z"}
    ROW = {"schema": 1, "at": "2026-10-19T09:00:00Z", "kind": "formed", "slot": "tollman-hal2", "train": "07@x",
           "cars": [{"field": "07", "branch": "07", "head": "7" * 40, "plan": ""}], "base": "b" * 40}

    def plan(self, rows, held):
        return trains.plan(self.TOP, self.MAIN, [], rows, {}, alive=lambda pid: False, result=lambda main: None,
                           held=held)

    def test_a_formed_train_is_not_restarted_while_held(self):
        self.assertEqual(held_kinds(self.plan([self.ROW], self.HELD)), ["held"])
        self.assertEqual(held_kinds(self.plan([self.ROW], None)), ["restart"])

    def test_the_held_line_names_the_reason(self):
        (line,) = self.plan([], self.HELD)
        self.assertEqual((line["do"], "key" in line), ("record", False))
        self.assertIn("held: x", line["text"])


if __name__ == "__main__":
    unittest.main()
