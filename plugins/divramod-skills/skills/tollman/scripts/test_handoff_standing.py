"""Hal2 plan 0611 step 7 (design.md §5): the tollman's handoff against its open standing orders (the CONTRA words of
records_kinds), through the shared handoff check of the farmer frame."""

import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import handoff
import standing
import tollman
from test_orders import Red

WORDS = "the user, 2026-11-05: every hitched wagon rides"


class Handoff(Red):
    def problems(self, text: str) -> list[str]:
        f = handoff.path(str(self.main), tollman.WIRING)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        return handoff.records_problems(str(self.main), tollman.WIRING)

    def test_every_wagon_rides_forbids_a_field_held_back(self):
        rec = standing.add(str(self.main), "every-wagon-rides", None, WORDS)["id"]
        bad = self.problems(f"{rec} stands.\nField 07 waits for the next train.\n")
        self.assertEqual(len(bad), 1)
        self.assertIn(f"goes against {rec}", bad[0])
        self.assertEqual(self.problems(f"{rec} stands.\nField 07 does not wait; field 09 is left out only because the user said so.\n"), [])
        self.assertEqual(self.problems(f"{rec} stands.\nField 07 rides the next train.\n"), [])

    def test_a_hold_forbids_trains_forming_and_the_open_record_must_be_named(self):
        rec = standing.add(str(self.main), "hold", "CI rebuild", WORDS)["id"]
        self.assertIn(f"{rec} (standing", self.problems("nothing here")[0])
        self.assertEqual(len(self.problems(f"{rec} hold is lifted, trains form.")), 1)
        self.assertEqual(self.problems(f"{rec} holds: no trains form until the user says."), [])


if __name__ == "__main__":
    unittest.main()
