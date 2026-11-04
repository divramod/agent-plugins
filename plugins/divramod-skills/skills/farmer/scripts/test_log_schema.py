"""Hal2 plan 0593 step 7: the journal (log.jsonl) is the store skill.farmer/log; every line `mtm_scan.log` writes carries
`schema` 1 and the keys schemas/log.schema.json requires, and the reader still takes legacy lines without it."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mtm_scan

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas/log.schema.json").read_text())


class LogSchema(unittest.TestCase):
    def test_new_lines_carry_the_schema(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(mtm_scan, "state_dir", return_value=Path(d)):
                mtm_scan.log("x", {"kind": "decision", "slot": "69", "what": "w"})
            line = json.loads((Path(d) / "log.jsonl").read_text().splitlines()[0])
        self.assertEqual(line["schema"], SCHEMA["properties"]["schema"]["maximum"])
        for key in SCHEMA["required"]:
            self.assertIn(key, line)
        self.assertLessEqual(set(line), set(SCHEMA["properties"]))

    def test_legacy_lines_without_schema_still_read(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "log.jsonl"
            f.write_text(json.dumps({"at": "2026-10-01T10:00:00Z", "kind": "ask"}) + "\n")
            self.assertEqual(mtm_scan.entries(f)[0]["kind"], "ask")


if __name__ == "__main__":
    unittest.main()
