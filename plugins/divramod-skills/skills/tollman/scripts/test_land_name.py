"""The land branch's name before every push (land_name.py, the user 2026-11-04): land/<NN> or land/train-<n>-<a> of
the standing train, else refused; train 51's land/tollman-train-big-0514-0581-28 never again."""
# enforces .adr/tollman.md

import contextlib
import io
import unittest
from unittest import mock

import land_name

CARRIER = "tollman-train"


def queue(name=None, carrier=CARRIER):
    return {"trains": [{"number": 51, "attempt": 2, "name": name, "carrier": carrier, "cars": []}] if name else []}


class Name(unittest.TestCase):
    def test_the_marked_train_lands_on_its_number(self):
        self.assertEqual(land_name.branch(CARRIER, None, queue("train-51-2")), "land/train-51-2")
        self.assertIsNone(land_name.why_bad("land/train-51-2", 51))

    def test_an_unmarked_carrier_falls_back_and_is_refused(self):
        name = land_name.branch("tollman-train-big-0514-0581-28", None, queue())
        self.assertEqual(name, "land/tollman-train-big-0514-0581-28")
        self.assertIn("mark", land_name.why_bad(name, 51))

    def test_another_carriers_mark_does_not_count(self):
        self.assertEqual(land_name.branch(CARRIER, None, queue("train-51-2", carrier="x")), f"land/{CARRIER}")

    def test_a_field_lands_on_its_number_and_names_are_exact(self):
        self.assertIsNone(land_name.why_bad("land/07", None))
        for bad in ("land/7", "land/train-0383-0365", "land/train-51", "land/train-51-2-x", "land/07-ui", "train-51-2"):
            self.assertIsNotNone(land_name.why_bad(bad, 51), bad)

    def test_a_mark_of_another_train_is_refused(self):
        self.assertIn("standing train is 51", land_name.why_bad("land/train-50-3", 51))

    def test_an_unreadable_queue_is_refused(self):
        self.assertEqual(land_name.why_bad(land_name.branch(CARRIER, None, None), 51), "the merge queue could not be read")

    def test_refuses_prints_the_line_and_the_result(self):
        with mock.patch.object(land_name.mtm_scan, "main_checkout", lambda top: top), \
                mock.patch.object(land_name.train_state, "lines", lambda main: [
                    {"kind": "formed", "train": "T", "number": 51, "cars": []}]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(land_name.refuses(f"/x/{CARRIER}", read=lambda top: queue()), 1)
                self.assertEqual(land_name.refuses(f"/x/{CARRIER}", read=lambda top: queue("train-51-3")), 0)
            self.assertIn('"status": "refused"', out.getvalue())
            self.assertEqual([x[:16] for x in out.getvalue().splitlines()].count("tollman: refused"), 1)


if __name__ == "__main__":
    unittest.main()
