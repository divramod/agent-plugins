"""Hal2 plan 0409 step 15: the tollman publishes a public farm's mirror after a train (mirror.py), with a fake
hal2-cli-git: public off says nothing, a publish names itself, a refusal is said and never raises."""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mirror

FAKE = """#!/usr/bin/env bash
[ "$2" = --help ] && exit "${HELP:-0}"
echo "$*" >> "$LOG"
printf '%b' "$SAYS"
exit "${CODE:-0}"
"""


class Publish(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        cli = self.dir / "cli"
        cli.write_text(FAKE)
        cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
        self.env = {"HAL2_CLI_GIT": str(cli), "LOG": str(self.dir / "log")}

    def run_with(self, **env):
        with mock.patch.dict(os.environ, {**self.env, **env}):
            return mirror.publish("/yard")

    def test_public_off_says_nothing_and_a_publish_names_itself(self):
        self.assertEqual(self.run_with(SAYS="publish: skipped (source a)\\nnote: off\\n"), "")
        self.assertEqual(self.run_with(SAYS="publish: published (source a)\\ngoes: 3\\n"), "; publish: published (source a)")
        self.assertEqual((self.dir / "log").read_text().splitlines(), ["publish --repo /yard"] * 2)

    def test_a_refusal_is_said_and_an_old_binary_is_left_alone(self):
        said = self.run_with(SAYS="publish: refused\\n", CODE="17")
        self.assertEqual(said, "; publish refused or failed (exit 17), the mirror is not updated: publish: refused")
        self.assertEqual(self.run_with(HELP="2"), "")
        self.assertEqual(self.run_with(HAL2_CLI_GIT=str(self.dir / "none")), "")

    def test_no_binary_on_path_or_one_that_cannot_run_publishes_nothing(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.dir / "empty")}):
            os.environ.pop("HAL2_CLI_GIT", None)
            self.assertEqual(mirror.publish("/yard"), "")
        broken = self.dir / "broken"
        broken.write_text("#!/nonexistent/interpreter\n")
        broken.chmod(broken.stat().st_mode | stat.S_IEXEC)
        self.assertEqual(self.run_with(HAL2_CLI_GIT=str(broken)), "")


if __name__ == "__main__":
    unittest.main()
