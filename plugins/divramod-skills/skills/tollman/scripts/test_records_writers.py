"""Hal2 plan 0611 step 3 (design.md §2, D4, D8, D10, D13): every tollman action command writes its record, in the
same call as its train line, which the record names; there is no record verb. Each command here leaves exactly one
open record of its kind in `roles/tollman/records.jsonl`; a refused command leaves none. Whole commands on
engine_farm.py's farm (test_orders.Red: a red train of the cars 07 and 09)."""

import contextlib
import io
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import acks
import engine
import field_pause
import foreman_wake
import records_kinds
import role_records
import train_state
import trains
from engine_farm import Farm
from test_orders import RUN, Red

WORDS = "take 09 out, its test is broken (the user)"


class Records:
    """What the records store holds after a command."""

    def opened(self, type=None):
        return [r for r in role_records.open_(str(self.main), records_kinds.ROLE) if type in (None, r["type"])]

    def one(self, type, slot):
        """Exactly one open record, of `type` for `slot`; returned."""
        recs = self.opened()
        self.assertEqual([(r["type"], r["slot"]) for r in recs], [(type, slot)], recs)
        return recs[0]

    def named(self, rec, kind):
        """The record names a train line of `kind` that exists (D10)."""
        self.assertEqual((rec["event"]["file"], rec["event"]["kind"]), ("train.jsonl", kind))
        self.assertIn(kind, [e["kind"] for e in train_state.lines(str(self.main))])


class OnARedTrain(Red, Records):
    def test_a_fix_order_opens_a_fix_order_record_naming_its_order_line(self):
        self.assertEqual(self.call("order", "07", "--why", "its test fails", "--run", RUN)[0], 0)
        rec = self.one("fix-order", "07")
        self.named(rec, "order")
        self.assertEqual((rec["order"], rec["event"]["id"], rec["by"], rec["id"]), ("07-fix-1", "07-fix-1", "tollman",
                                                                                    "R1"))

    def test_the_user_s_unhitch_opens_a_user_order_with_the_user_s_words(self):
        code, text = self.call("unhitch", "09", "--why", "its test fails", "--by-user", repo=self.main)
        self.assertEqual(code, 1, text)
        self.assertIn("--words", text)
        self.assertEqual(self.opened(), [], "refused without the user's words: nothing written")
        code, text = self.call("unhitch", "09", "--why", "its test fails", "--by-user", "--words", WORDS,
                               repo=self.main)
        self.assertEqual(code, 0, text)
        rec = self.one("user-order", "09")
        self.named(rec, "unhitched")
        self.assertEqual((rec["by"], rec["words"], rec["order"]), ("user", WORDS, "unhitch"))

    def test_the_user_s_breakup_opens_a_user_order(self):
        self.alive.clear()
        carrier, name = self.train_name_carrier, self.name
        base = ["breakup", "--why", "the user breaks it up", "--by-user", "--repo", str(self.wm)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(engine.main(base), 1, "no words: refused")
            self.assertEqual(self.opened(), [])
            self.assertEqual(engine.main(base + ["--words", WORDS]), 0)
        rec = self.one("user-order", carrier)
        self.named(rec, "cleared")
        self.assertEqual((rec["by"], rec["words"], rec["order"], rec["train"]), ("user", WORDS, "breakup", name))

    def test_a_retry_opens_a_restart_record_of_the_train(self):
        self.assertEqual(self.call("retry", "--why", "flaky: tmux_attach")[0], 0)
        rec = self.one("restart", self.train_name_carrier)
        self.named(rec, "retry")
        self.assertEqual((rec["of"], rec["train"]), ("train", self.name))

    def test_a_started_train_takes_no_join_and_opens_no_hand_merge(self):
        """Plan 0687 D1, D4: a train's cars are fixed at its first start; a later wagon rides the next train, the
        round's join and a join by hand alike, so no hand-merge record opens."""
        with mock.patch.object(trains, "PROVE", lambda *a: {"state": "green", "lines": []}):
            self.crop("11", {"eleven.txt": "11"})
            self.round()
            self.assertNotIn("11", [c["field"] for c in self.train()["cars"]])
            self.crop("12", {"twelve.txt": "12"})
            code, text = self.call("join", "12")
        self.assertEqual(code, 1, text)
        self.assertIn("rides the next train", text)
        self.assertNotIn("12", [c["field"] for c in self.train()["cars"]])
        self.assertEqual(self.opened(), [])

    @property
    def name(self):
        return self.train()["train"]

    @property
    def train_name_carrier(self):
        return self.train()["carrier"]


class WithoutATrain(Farm, Records):
    def test_the_barn_s_own_fix_order_opens_a_fix_order_record(self):
        self.assertEqual(self.call("order", "main", "--why", "the barn is red")[0], 0)
        rec = self.one("fix-order", "main")
        self.named(rec, "order")
        self.assertEqual(rec["order"], "main-fix-1")

    def test_restart_starts_the_field_and_opens_a_restart_record(self):
        seen = []
        guard = lambda argv: seen.append(argv) or 0  # noqa: E731  (never a real session)
        with mock.patch.object(field_pause, "load", lambda main: {"27": {"by": "the user", "why": "away"}}):
            code, text = foreman_wake.restart(str(self.main), "27", "its fix order waits", guard=guard)
            self.assertEqual((code, seen, self.opened()), (1, [], []), text)
        with mock.patch.object(field_pause, "load", lambda main: {}):
            self.assertEqual(foreman_wake.restart(str(self.main), "27", "x", guard=lambda a: 75)[0], 75)
            self.assertEqual(self.opened(), [], "a skipped start: no record")
            code, text = foreman_wake.restart(str(self.main), "27", "its fix order waits", guard=guard)
        self.assertEqual(code, 0, text)
        self.assertEqual(seen[0][seen[0].index("--") + 1:][:4], ["hal2-cli-git", "worktree", "run", "27"])
        rec = self.one("restart", "27")
        self.named(rec, "woke")
        self.assertEqual(rec["of"], "session")
        self.assertIn(rec["id"], text)

    def test_the_restart_verb_is_tollman_s(self):
        with mock.patch.object(foreman_wake, "restart", lambda repo, field, why: (0, f"{field}: {why}")):
            self.assertEqual(self.call("restart", "27", "--why", "asleep"), (0, "27: asleep\n"))

    def test_a_question_sent_with_acks_instruct_opens_a_question_record(self):
        with contextlib.redirect_stdout(io.StringIO()):
            acks.main(["instruct", "16", "is the fix pushed?", "--role", "farmer", "--repo", str(self.main)])
            self.assertEqual(self.opened(), [], "the farmer keeps no question records (yet)")
            acks.main(["instruct", "16", "is the fix pushed?", "--role", "tollman", "--repo", str(self.main)])
        rec = self.one("question", "16")
        asks = [e for e in self.wm_log() if e.get("kind") == "ask-ack"]
        self.assertEqual((rec["ack"], rec["event"]), (asks[-1]["id"], {"file": "log.jsonl", "kind": "ask-ack",
                                                                         "id": asks[-1]["id"]}))
        self.assertIn("is the fix pushed?", rec["what"])

    def test_no_record_verb(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for verb in ("record", "records", "close"):
                with self.assertRaises(SystemExit):
                    self.call(verb, "R1")


if __name__ == "__main__":
    unittest.main()
