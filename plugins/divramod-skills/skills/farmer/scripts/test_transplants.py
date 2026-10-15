import datetime as dt
import json
import unittest

import transplants

ENTRY = dt.datetime(2026, 10, 13, 10, 0)  # naive local, as the ledger writes its `at`


def at(minutes: int) -> str:
    """A record's RFC 3339 UTC time `minutes` after the entry."""
    return (ENTRY.astimezone() + dt.timedelta(minutes=minutes)).astimezone(dt.timezone.utc).isoformat()


def record(src, dst, minutes, state="arrived", id=None):
    return {"id": id or f"{src}-to-{dst}", "from": src, "to": dst, "state": state, "driven": at(minutes),
            "plan": "0273-x", "by": "main"}


def cli(records, code=0):
    def call(argv, cwd):
        assert argv == ["hal2-cli-git", "worktree", "transplants", "--json"], argv
        return code, json.dumps({"transplants": records})
    return call


class Moved(unittest.TestCase):
    def test_a_transplanted_field_is_followed_to_its_target(self):
        for state in ("driven", "arrived"):
            self.assertEqual(transplants.moved("/x/hal2", "34", ENTRY, cli([record("34", "09", 5, state)])), "09")

    def test_two_transplants_in_a_row_end_in_the_last_target(self):
        records = [record("09", "12", 90), record("34", "09", 5)]  # newest first, as the CLI prints them
        self.assertEqual(transplants.moved("/x/hal2", "34", ENTRY, cli(records)), "12")
        self.assertEqual(transplants.follow(records, "34", ENTRY), ("12", "09-to-12"))

    def test_the_second_hop_must_come_after_the_first(self):
        records = [record("09", "12", 1), record("34", "09", 5)]
        self.assertEqual(transplants.moved("/x/hal2", "34", ENTRY, cli(records)), "09")

    def test_a_round_trip_is_a_move(self):
        records = [record("09", "34", 90), record("34", "09", 5)]
        self.assertEqual(transplants.moved("/x/hal2", "34", ENTRY, cli(records)), "34")

    def test_a_field_no_transplant_names_stays_where_it_is(self):
        self.assertIsNone(transplants.moved("/x/hal2", "18", ENTRY, cli([record("34", "09", 5)])))
        self.assertIsNone(transplants.moved("/x/hal2", "18", ENTRY, cli([])))

    def test_a_transplant_older_than_the_entry_is_not_its_own(self):
        self.assertIsNone(transplants.moved("/x/hal2", "34", ENTRY, cli([record("34", "09", -30)])))

    def test_a_prepared_or_cancelled_transplant_moved_nothing(self):
        for state in ("prepared", "cancelled"):
            r = {**record("34", "09", 5, state)}
            r.pop("driven")
            self.assertIsNone(transplants.moved("/x/hal2", "34", ENTRY, cli([r])))

    def test_a_cli_without_the_command_or_with_other_output_says_not_moved(self):
        self.assertIsNone(transplants.moved("/x/hal2", "34", ENTRY, lambda argv, cwd: (2, "unknown subcommand")))
        self.assertIsNone(transplants.moved("/x/hal2", "34", ENTRY, lambda argv, cwd: (127, "no such file")))
        self.assertIsNone(transplants.moved("/x/hal2", "34", ENTRY, lambda argv, cwd: (0, "not json")))
        self.assertIsNone(transplants.moved("/x/hal2", "34", ENTRY, lambda argv, cwd: (0, json.dumps([1]))))
        self.assertIsNone(transplants.moved("/x/hal2", "34", ENTRY, lambda argv, cwd: (0, json.dumps({"transplants": 3}))))
        self.assertIsNone(transplants.moved("/x/hal2", "34", ENTRY, cli([{"from": "34", "state": "driven"}])))

    def test_a_chain_that_loops_ends(self):
        records = [record("34", "09", 5 + i * 10, id=f"r{i}") if i % 2 == 0 else record("09", "34", 5 + i * 10, id=f"r{i}")
                   for i in range(6)]
        self.assertIn(transplants.moved("/x/hal2", "34", ENTRY, cli(records)), ("09", "34"))


if __name__ == "__main__":
    unittest.main()
