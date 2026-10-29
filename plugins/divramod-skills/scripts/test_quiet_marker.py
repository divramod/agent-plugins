"""quiet_marker: the marker of hal2-core's shape read as the Rust reader reads it, in a scratch state root."""
import json
import tempfile
import unittest
from pathlib import Path

import quiet_marker


class QuietMarker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {"HAL2_STATE_DIR": self.tmp.name}
        self.path = Path(self.tmp.name) / "quiet.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_state_root_follows_hal2_core(self):
        self.assertEqual(quiet_marker.marker(self.env), self.path)
        self.assertEqual(quiet_marker.state_root({"XDG_STATE_HOME": "/x"}), Path("/x/hal2"))
        self.assertEqual(quiet_marker.state_root({"HAL2_HOME": "/h", "HOME": "/u"}), Path("/h", *quiet_marker.DEFAULT_STATE))

    def test_no_marker_a_broken_or_foreign_one_is_no_quiet(self):
        self.assertIsNone(quiet_marker.refusal(self.env))
        self.path.write_text("{not json")
        self.assertIsNone(quiet_marker.refusal(self.env))
        self.path.write_text(json.dumps({"schema": 2, "active": True}))
        self.assertIsNone(quiet_marker.refusal(self.env))

    def test_quiet_now_refuses_a_hold_alone_does_not(self):
        self.path.write_text(json.dumps({"schema": 1, "active": False, "holds": {"mac_vm": {
            "at": "2026-10-28T09:00:01Z", "by": "v", "why": "w"}}}))
        self.assertIsNone(quiet_marker.refusal(self.env))
        self.path.write_text(json.dumps({"schema": 1, "active": True, "since": "2026-10-28T09:00:00Z",
                                         "by": "hal2-cli-machine", "holds": {}}))
        why = quiet_marker.refusal(self.env)
        self.assertIn("the machine is quiet since 2026-10-28T09:00:00Z by hal2-cli-machine", why)
        self.assertIn(str(self.path), why)


if __name__ == "__main__":
    unittest.main()
