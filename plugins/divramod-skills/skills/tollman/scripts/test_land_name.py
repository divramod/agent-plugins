"""The land branch's name is asked of hal2-git (land_name.py, plan 0607 step 6, the user 2026-11-04): the CLI's
`worktree land-ref --json` (schema 1) is the only source; a train's carrier without its numbered mark, a bad schema or
no answer is refused before every push; train 51's land/tollman-train-big-0514-0581-28 never again. The fixtures in
fixtures/land_ref/ are what hal2-cli-git prints (field.json and error.json from the built CLI in field 77, train.json
the same shape for a marked carrier); no real CLI call here."""
# enforces .adr/tollman.md

import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest import mock

import land_name

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "land_ref"
CARRIER = "tollman-hal2"


def fixture(name):
    return (FIXTURES / f"{name}.json").read_text().strip()


def answers(text, code=0):
    return lambda args, cwd: (code, text)


class Ask(unittest.TestCase):
    def test_the_command_is_land_ref_with_the_slot_and_json_run_in_the_checkout(self):
        seen = []
        land_name.ask("/farm/x", CARRIER, run=lambda args, cwd: seen.append((args, cwd)) or (0, fixture("train")))
        land_name.ask("/farm/x", run=lambda args, cwd: seen.append((args, cwd)) or (0, fixture("field")))
        self.assertEqual(seen, [(["worktree", "land-ref", "--slot", CARRIER, "--json"], "/farm/x"),
                                (["worktree", "land-ref", "--json"], "/farm/x")])

    def test_the_cli_s_json_is_read_by_its_keys(self):
        report, why = land_name.ask("/x", run=answers(fixture("train")))
        self.assertEqual((why, report["kind"], report["current"], report["next"]),
                         ("", "train", "land/train-51-1", "land/train-51-2"))
        self.assertEqual(land_name.next_ref("/x", run=answers(fixture("train"))), ("train-51-2", ""))
        self.assertEqual(land_name.current("/x", run=answers(fixture("train"))), "land/train-51-1")
        self.assertIsNone(land_name.current("/x", run=answers(fixture("field"))), "null before any landing")

    def test_a_refusal_is_the_cli_s_one_line_json_or_not(self):
        self.assertEqual(land_name.ask("/x", run=answers(fixture("error"), 1)),
                         (None, "main is not a worktree: it lands nothing"))
        self.assertEqual(land_name.ask("/x", run=answers("error: not a repository", 1)), (None, "error: not a repository"))
        self.assertEqual(land_name.next_ref("/x", run=answers(fixture("error"), 1))[0], None)
        self.assertIsNone(land_name.current("/x", run=answers(fixture("error"), 1)))

    def test_an_unknown_schema_a_missing_key_and_no_json_are_refused(self):
        bad = json.loads(fixture("train"))
        self.assertIn("schema 2", land_name.ask("/x", run=answers(json.dumps({**bad, "schema": 2})))[1])
        self.assertIn("schema ?", land_name.ask("/x", run=answers("[]"))[1])
        self.assertIn("lacks next", land_name.ask("/x", run=answers(json.dumps({k: v for k, v in bad.items() if k != "next"})))[1])
        self.assertEqual(land_name.ask("/x", run=answers("hi"))[0], None)


class Why(unittest.TestCase):
    def report(self, name="train"):
        return json.loads(fixture(name))

    def test_the_marked_carrier_of_the_standing_train_is_fine(self):
        self.assertIsNone(land_name.why_bad(self.report(), "", None, 51))
        self.assertIsNone(land_name.why_bad(self.report(), "", "train-51-2", 51))

    def test_what_the_cli_cannot_name_is_refused_with_its_words(self):
        self.assertEqual(land_name.why_bad(None, "the carrier has no mark", None, 51), "the carrier has no mark")

    def test_a_field_s_name_is_no_train_s(self):
        self.assertIn("no numbered train mark", land_name.why_bad(self.report("field"), "", None, 51))

    def test_another_train_s_mark_and_another_land_ref_are_refused(self):
        self.assertEqual(land_name.why_bad(self.report(), "", None, 50), "the standing train is 50")
        self.assertIn("names land/train-51-1", land_name.why_bad(self.report(), "", "train-51-1", 51))


class Refuses(unittest.TestCase):
    def refuses(self, read, ref=None):
        out = io.StringIO()
        with mock.patch.object(land_name.mtm_scan, "main_checkout", lambda top: top), \
                mock.patch.object(land_name.train_state, "lines", lambda main: [
                    {"kind": "formed", "train": "T", "number": 51, "cars": []}]), contextlib.redirect_stdout(out):
            return land_name.refuses(f"/x/{CARRIER}", ref, read=read), out.getvalue()

    def test_a_marked_carrier_passes_silently(self):
        self.assertEqual(self.refuses(lambda top: land_name.ask(top, run=answers(fixture("train")))), (0, ""))

    def test_a_carrier_without_its_mark_is_refused_with_the_line_and_the_result(self):
        read = lambda top: land_name.ask(top, run=answers(json.dumps({"error": {"message": "no numbered mark"}}), 1))
        code, text = self.refuses(read)
        self.assertEqual(code, 1)
        self.assertIn("tollman: refused: the landing would push a branch: no numbered mark", text)
        self.assertIn('"status": "refused"', text)
        self.assertEqual([x[:16] for x in text.splitlines()].count("tollman: refused"), 1)

    def test_another_trains_number_is_refused_naming_the_cli_s_branch(self):
        code, text = self.refuses(lambda top: land_name.ask(top, run=answers(fixture("train").replace("51-2", "50-2"))))
        self.assertEqual(code, 1)
        self.assertIn("land/train-50-2: the standing train is 51", text)

    def test_an_explicit_land_ref_must_be_the_cli_s(self):
        read = lambda top: land_name.ask(top, run=answers(fixture("train")))
        self.assertEqual(self.refuses(read, "train-51-2"), (0, ""))
        self.assertEqual(self.refuses(read, "train-0383-0365")[0], 1)


if __name__ == "__main__":
    unittest.main()
