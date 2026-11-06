"""Hal2 plan 0717 step 2 (D3, tollman learning L265): train 56-5's run end replayed. Two cars, each order answered
twice (an older and a newer sha): only the newest of each is proven; the older gets no proof run and no refusal sent
to its foreman. The farm is test_orders.py's (cars 07 and 09 stand for 56-5's 19 and 00)."""

import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import acks
import orders_newest
import train_state
import test_orders


class Replay(test_orders.Proof):
    def setUp(self):
        super().setUp()
        self.asks = {}

    def order_and_answer(self, field):
        """An order for `field` answered with an older sha, then a newer one (the foreman's second answer)."""
        self.call("order", field, "--why", "python-lint: x.py:1:1: E501", "--job", "python-lint",
                  "--unit", f"{field}.py")
        self.asks[field] = self.typed[-1][1].split("]")[0].removeprefix("tollman [")
        old = self.fix(field, text="old")
        self.ack_for(field, old)
        new = self.fix(field, text="new")
        self.ack_for(field, new)
        return old, new

    def ack_for(self, field, sha):
        self.assertEqual(acks.main(["ack", self.asks[field], "done", "fixed", sha, "--repo", str(self.wm), "--role",
                                    "tollman"]), 0)

    def test_only_the_newest_sha_of_each_order_is_proven_the_older_never_refused(self):
        olds, news = zip(self.order_and_answer("07"), self.order_and_answer("09"))
        told = len(self.typed)
        self.round()  # the proof of each newest starts (here: runs at once)
        self.assertEqual(sorted(sha for _, sha in self.proved), sorted(news), "no proof of an older sha")
        for old in olds:
            self.assertNotIn(old, [sha for _, sha in self.proved])
        self.round()
        self.assertEqual(self.train()["state"], "retry", "both newest taken")
        taken = [e["sha"] for e in train_state.lines(str(self.main)) if e["kind"] == "fixed"]
        self.assertEqual(sorted(taken), sorted(news))
        self.assertEqual([t for t in self.typed[told:] if "refused" in t[1].lower()], [], "no refusal sent")

    def test_a_fixed_for_an_older_answer_is_superseded_silently(self):
        old, new = self.order_and_answer("07")
        told = len(self.typed)
        code, text = self.call("fixed", "07", old)
        self.assertEqual(code, 0, text)
        self.assertIn("superseded by " + new[:12], text)
        self.assertEqual((self.proved, len(self.typed)), ([], told), "no proof run, no message to the foreman")
        self.assertEqual(self.train()["state"], "fixing", "the order stays open for the newer answer")


for _name in dir(test_orders.Proof):  # the inherited farm tests run in test_orders.py, not twice
    if _name.startswith("test_") and _name not in Replay.__dict__:
        setattr(Replay, _name, None)


class Pure(unittest.TestCase):
    LOG = [{"kind": "ask-ack", "id": "a1", "text": "fix order o1 x"},
           {"kind": "ack", "id": "a1", "what": "done", "note": "fixed " + "a" * 12},
           {"kind": "ack", "id": "a1", "what": "done", "note": "fixed " + "b" * 12}]

    def test_the_taken_sha_wins_else_the_last_answer(self):
        self.assertEqual(orders_newest.newest("o1", [], self.LOG), "b" * 12)
        rows = [{"kind": "fixed", "id": "o1", "sha": "a" * 40}]
        self.assertEqual(orders_newest.newest("o1", rows, self.LOG), "a" * 40, "the taken one when taken")
        self.assertIsNone(orders_newest.newest("o2", [], self.LOG))

    def test_only_an_older_answer_is_superseded(self):
        self.assertEqual(orders_newest.superseded("o1", "a" * 40, [], self.LOG), "b" * 12)
        self.assertIsNone(orders_newest.superseded("o1", "b" * 40, [], self.LOG))
        self.assertIsNone(orders_newest.superseded("o1", "c" * 40, [], self.LOG), "never answered: no answer")


if __name__ == "__main__":
    unittest.main()
