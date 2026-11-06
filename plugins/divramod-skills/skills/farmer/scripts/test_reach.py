"""Plan 0695 step 40 (D41 H8): relays and orders reach a session by its pane, never a name."""

import io
import json
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import acks
import deliver
import mtm_scan
import reach
import tick

AGENTS = {"agents": [{"pane_id": "%7", "slot": "02", "project": "/y", "state": "working"},
                     {"pane_id": "%9", "slot": "02", "project": "/other"}]}


class Reach(unittest.TestCase):
    def test_the_pane_is_found_by_slot_and_this_farm_s_checkout(self):
        self.assertEqual(reach.pane_in(AGENTS["agents"], "02", "/y/"), "%7")
        self.assertIsNone(reach.pane_in(AGENTS["agents"], "03", "/y"))

    def test_a_busy_session_is_reached_by_its_pane(self):
        calls = []
        with mock.patch.object(deliver, "cli", return_value=(0, json.dumps(AGENTS))), \
                mock.patch.object(deliver, "send", side_effect=lambda p, t, s: calls.append((p, t, s))):
            self.assertEqual(reach.send("02", "/y", "go"), ("%7", None))
        self.assertEqual(calls, [("%7", "go", reach.BUSY)])
        self.assertIn("working", reach.BUSY)

    def test_no_session_is_said(self):
        with mock.patch.object(deliver, "cli", return_value=(1, "")):
            self.assertEqual(reach.send("02", "/y", "go"), (None, "no session"))

    def test_a_relay_is_typed_not_handed_to_a_name(self):
        out = {}
        a = tick.act("trains", "car-red", "relay", "02", text="fix it", key="k")
        with mock.patch.object(reach, "send", return_value=("%7", None)), mock.patch.object(mtm_scan, "log"):
            tick.execute(a, "/x/farmer", "/y", out)
        self.assertNotIn("relay", out)
        self.assertEqual((a["delivered"], "to" in a), ("%7", False))

    def test_a_refused_relay_reaches_the_farmer_with_its_pane(self):
        out = {}
        a = tick.act("trains", "car-red", "relay", "02", text="fix it", key="k")
        with mock.patch.object(reach, "send", return_value=("%7", "draft")), mock.patch.object(mtm_scan, "log"):
            tick.execute(a, "/x/farmer", "/y", out)
        self.assertEqual([(r["pane"], "to" in r) for r in out["relay"]], [("%7", False)])

    def test_instruct_send_types_by_pane(self):
        with mock.patch.object(reach, "send", return_value=("%7", None)) as send, \
                mock.patch.object(mtm_scan, "main_checkout", return_value="/y"), \
                mock.patch.object(mtm_scan, "entries", return_value=[]), mock.patch.object(mtm_scan, "log"), \
                mock.patch.object(mtm_scan, "state_dir", return_value=Path("/nonexistent")), \
                mock.patch.object(acks, "question"), redirect_stderr(io.StringIO()) as err, \
                mock.patch("sys.stdout", io.StringIO()):
            acks.main(["instruct", "02", "go on", "--send", "--repo", "/y"])
        self.assertEqual(send.call_args.args[:2], ("02", "/y"))
        self.assertIn("sent to %7", err.getvalue())


if __name__ == "__main__":
    unittest.main()
