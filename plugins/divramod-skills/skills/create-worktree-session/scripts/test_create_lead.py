#!/usr/bin/env python3
"""A field holding plans/LEAD is a servant's, whatever its number (hal2 plan 0383, D16): a foreman's start skips it and
takes the next free field, even in 30-99; only `--role servant` takes it (offline, with test_create's fake hal2 CLIs)."""
import unittest

import test_create

Fake = test_create.TestCreate


class TestServantFields(unittest.TestCase):
    setUp, tearDown, run_create, run_raw, refused, run_call = (
        Fake.setUp, Fake.tearDown, Fake.run_create, Fake.run_raw, Fake.refused, Fake.run_call)

    def mark(self, slot: str) -> None:
        """The worktree `slot` (a real folder under the fake worktree base) holds a foreman's marker."""
        (self.wt / slot / "plans").mkdir(parents=True)
        (self.wt / slot / "plans" / "LEAD").write_text("07 0383-train-rules 16\n")

    def test_a_foreman_takes_field_30_when_it_is_free_and_skips_a_marked_one(self):
        self.assertEqual(self.run_create("--from", "30", extra="30,31")["slot"], "30")
        self.log.unlink()
        self.mark("30")
        out = self.run_create("--from", "30", extra="30,31")
        self.assertEqual((out["slot"], out["skipped"]), ("31", [{"slot": "30", "why": "a servant's field (plans/LEAD)"}]))

    def test_a_marked_field_below_30_is_a_servants_too(self):
        self.mark("05")
        out = self.run_create("--from", "05", "--to", "06", extra="05")
        self.assertEqual(out["slot"], "06", "the number says nothing, the marker does")

    def test_a_servant_start_takes_a_marked_field(self):
        self.mark("30")
        out = self.run_create("--from", "30", "--role", "servant", extra="30,31")
        self.assertEqual((out["slot"], out["skipped"]), ("30", []))


if __name__ == "__main__":
    unittest.main()
