"""Hal2 plan 0717 step 1 (tollman learning L265): train 56-5's run end replayed. Cars 19 and 00; field 49 is paused
and no car; `00-fix-3` closed the red `fixed`. Run triage ordered 49 for it all the same. Now a field that is no
car never owns a red (the board note of the no-owner path) and a red a fixed order of the train covers gets none."""
# enforces .adr/tollman.md

import unittest

import run_triage_act as dispatch
import run_triage_dedup as dedup_

URL = "https://github.com/divramod/hal2/actions/runs/5600"
RUN = {"id": "5600", "url": URL, "at": "2026-11-06T10:00:00Z"}
TRAIN = {"train": "train-56-5", "carrier": "19", "cars": [{"field": "19"}, {"field": "00"}]}
JOB = "stack-test"


def red(owner: str, job: str = JOB) -> dict:
    return {"key": f"triage:5600:{job}", "kind": "file", "cause": "file", "owner": owner, "live": True,
            "evidence": {"run": URL, "id": "5600", "job": job, "unit": job, "tests": [], "lines": [], "cars": ["19", "00"],
                         "owner": {"field": owner}}, "reproduce": "r", "reproduced": False}


ROWS = [
    {"kind": "order", "train": "train-56-5", "id": "o3", "field": "00", "jobs": [JOB], "why": "stack-test red",
     "run": "5599", "at": "2026-11-06T09:00:00Z"},
    {"kind": "order", "train": "train-56-4", "id": "o9", "field": "49", "jobs": [JOB], "why": "x", "run": "1"},
    {"kind": "fixed", "train": "train-56-5", "id": "o3", "slot": "00", "at": "2026-11-06T10:30:00Z"},
    {"kind": "fixed", "train": "train-56-4", "id": "o9", "slot": "49", "at": "2026-11-06T10:31:00Z"},
]


def plan(verdict: dict, closed: list[dict]) -> list[dict]:
    res = {"run": RUN, "verdicts": [verdict], "dedup": {"orders": [], "wagons": [], "plans": {}, "closed": closed}}
    return dispatch.actions("/f/tollman-hal2", "/f/main", res, TRAIN, None, {"49": "%49", "00": "%0"},
                            read=lambda *_: [])


class Train56x5(unittest.TestCase):
    def test_closed_reads_only_this_trains_fixed_orders(self):
        got = dedup_.closed(ROWS, "train-56-5")
        self.assertEqual([(o["id"], o["field"], o["jobs"]) for o in got], [("o3", "00", [JOB])])

    def test_a_red_a_fixed_order_covers_gets_no_order_and_no_note_to_a_non_car(self):
        out = plan(red("49"), dedup_.closed(ROWS, "train-56-5"))
        self.assertEqual([a["kind"] for a in out], ["triage-record"])
        self.assertIn("already closed it", out[0]["text"])

    def test_a_fixed_order_before_the_red_run_began_does_not_cover_a_later_red(self):
        old = [{**o, "at": "2026-11-06T09:30:00Z", "run": "5599"} for o in dedup_.closed(ROWS, "train-56-5")]
        out = plan(red("00"), old)
        self.assertEqual([a["kind"] for a in out], ["triage-order"])

    def test_a_non_car_never_owns_a_red(self):
        out = plan(red("49"), [])
        self.assertEqual([a["kind"] for a in out], ["triage-note"])
        self.assertTrue(out[0]["text"].endswith("no owner"))

    def test_a_car_still_gets_its_order(self):
        out = plan(red("00"), [])
        self.assertEqual([(a["kind"], a["slot"]) for a in out], [("triage-order", "00")])

    def test_another_job_of_the_closed_order_is_not_covered(self):
        out = plan(red("00", "desktop-e2e"), dedup_.closed(ROWS, "train-56-5"))
        self.assertEqual([a["kind"] for a in out], ["triage-order"])


if __name__ == "__main__":
    unittest.main()
