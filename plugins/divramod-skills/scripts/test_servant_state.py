"""servant_state: the reader runs `servant show --json` and trusts nothing else; servant_testkit's fake stands in."""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import servant_state
import servant_testkit as kit


class ServantState(unittest.TestCase):
    def setUp(self):
        kit.install(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_a_servant_is_read_with_every_step(self):
        kit.write(self.root, "09", "0594-servant-state", [("3", "three", "done"), ("4", "four", "")], finished=False)
        found = servant_state.of(self.root)
        self.assertEqual((found["foreman"], found["plan"], servant_state.step_names(found)), ("09", "0594-servant-state", ["3", "4"]))
        self.assertEqual(servant_state.foreman_of(self.root), "09")
        self.assertEqual(servant_state.steps_line(found), "steps 3 (done), 4 (open)")

    def test_one_step_reads_singular(self):
        kit.write(self.root, "09", "0594-x", [("3", "three", "in progress")])
        self.assertEqual(servant_state.steps_line(servant_state.of(self.root)), "step 3 (in progress)")

    def test_a_field_that_is_no_servant_is_none(self):
        self.assertIsNone(servant_state.of(self.root))
        self.assertIsNone(servant_state.foreman_of(self.root))

    def test_a_missing_cli_is_none_not_a_fallback(self):
        (self.root / "plans").mkdir()
        (self.root / "plans" / "LEAD").write_text("09 0594-x 3\n")
        with mock.patch.dict(os.environ, {"HAL2_CLI_PLANS": str(self.root / "nowhere")}):
            self.assertIsNone(servant_state.of(self.root))

    def test_garbage_failure_and_a_foreign_schema_are_none(self):
        fake = Path(os.environ["HAL2_CLI_PLANS"])
        for out, code in (("not json", 0), ('{"schema": 2, "foreman": "09", "plan": "p", "steps": []}', 0),
                          ('{"schema": 1, "foreman": "09", "plan": "p", "steps": []}', 1), ("[]", 0)):
            fake.write_text(f"#!/bin/sh\nprintf '%s' '{out}'\nexit {code}\n")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            self.assertIsNone(servant_state.of(self.root), out)

    def test_the_cli_is_asked_for_this_checkout(self):
        fake = Path(os.environ["HAL2_CLI_PLANS"])
        asked = self.root / "asked"
        fake.write_text(f"#!/bin/sh\necho \"$@\" > {asked}\necho null\n")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        servant_state.of(self.root)
        self.assertEqual(asked.read_text().split(), ["servant", "show", "--repo", str(self.root), "--json"])


if __name__ == "__main__":
    unittest.main()
