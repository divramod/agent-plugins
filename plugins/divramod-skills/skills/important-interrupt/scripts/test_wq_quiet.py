"""The workqueue quiet round trip (wq_quiet.py): stop turns `hal2-cli-workqueue quiet on`, done turns it off, only when
the interrupt turned it on. The CLI is a fake shell script in a temp dir that logs its argv and keeps a state file;
the machine, the sessions and quiet.py are the fakes of test_interrupt; nothing touches the user's state."""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import freeze
import interrupt
import stopall
import wq_quiet
from test_interrupt import Base

FAKE = """#!/bin/sh
echo "$@" >> "$FAKE_WQ_DIR/argv.log"
state="$FAKE_WQ_DIR/state"
case "$1 $2" in
  "quiet on") echo on > "$state" ;;
  "quiet off") echo off > "$state" ;;
  "quiet ") echo "quiet: $(cat "$state")" ;;
esac
[ -n "$FAKE_WQ_FAIL" ] && [ "$2" = "on" ] && { echo boom >&2; exit 3; }
exit 0
"""


class CliSys:
    """The fake machine for everything but the workqueue CLI, which really runs (the fake script)."""

    def __init__(self, fake, cli):
        self.fake, self.cli, self.real = fake, cli, freeze.Sys()

    def run(self, cmd, timeout=60):
        return (self.real if cmd[0] == self.cli else self.fake).run(cmd, timeout)

    def __getattr__(self, name):
        return getattr(self.fake, name)


class QuietRoundTrip(Base):
    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.bin = base / "bin"
        self.bin.mkdir()
        self.cli = self.bin / "hal2-cli-workqueue"
        self.cli.write_text(FAKE)
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        self.state = base / "state"
        self.state.write_text("off\n")
        self.env2 = {"FAKE_WQ_DIR": str(base), "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}
        self.saved = {k: os.environ.get(k) for k in (*self.env2, "HAL2_CLI_WORKQUEUE", "FAKE_WQ_FAIL")}
        os.environ.update(self.env2)
        os.environ.pop("HAL2_CLI_WORKQUEUE", None)
        os.environ.pop("FAKE_WQ_FAIL", None)
        self.sys = CliSys(self.sys, str(self.cli))

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        super().tearDown()

    def argv(self):
        log = Path(self.env2["FAKE_WQ_DIR"]) / "argv.log"
        return log.read_text().splitlines() if log.exists() else []

    def mode(self):
        return self.state.read_text().strip()

    def test_stop_then_done_round_trips_quiet(self):
        self.assertEqual(self.run_stop(), 0)
        self.assertEqual(self.mode(), "on")
        self.assertEqual(self.argv(), ["quiet", "quiet on"])
        state = json.loads(stopall.record().read_text())
        act = next(a for a in state["actions"] if a["text"] == "set workqueue quiet on")
        self.assertEqual(act["undo"], [str(self.cli), "quiet", "off"])
        self.assertEqual(state["important_interrupt"]["workqueue_quiet"]["set"], True)
        self.assertEqual(state["important_interrupt"]["workqueue_quiet"]["was"], "off")
        row = json.loads((interrupt.root() / "log.jsonl").read_text().splitlines()[-1])
        self.assertEqual(row["counts"]["quiet"], 1)
        self.assertEqual(interrupt.main(["done"], self.deps()), 0)
        self.assertEqual(self.mode(), "off")
        self.assertEqual(self.argv(), ["quiet", "quiet on", "quiet off"])
        self.assertTrue(any(line.startswith("undo set workqueue quiet on") and "(gone or failed)" not in line
                            for line in self.lines))

    def test_a_quiet_set_before_stays(self):
        self.state.write_text("on\n")
        self.assertEqual(self.run_stop(), 0)
        self.assertEqual(self.argv(), ["quiet"])  # read, never set
        state = json.loads(stopall.record().read_text())
        self.assertFalse(any("workqueue quiet" in a["text"] for a in state["actions"]))
        self.assertEqual(state["important_interrupt"]["workqueue_quiet"], {"cli": str(self.cli), "was": "on",
                                                                          "set": False})
        self.assertEqual(interrupt.main(["done"], self.deps()), 0)
        self.assertEqual(self.mode(), "on")
        self.assertEqual(self.argv(), ["quiet"])
        self.assertTrue(any("already on" in line for line in self.lines))

    def test_env_override_names_the_binary(self):
        other = self.bin / "other-wq"
        other.write_text(FAKE)
        other.chmod(0o755)
        os.environ["PATH"] = os.environ["PATH"].replace(str(self.bin) + os.pathsep, "")
        os.environ["HAL2_CLI_WORKQUEUE"] = str(other)
        self.sys.cli = str(other)
        self.assertEqual(self.run_stop(), 0)
        self.assertEqual(self.mode(), "on")
        self.assertEqual(interrupt.main(["done"], self.deps()), 0)
        self.assertEqual(self.mode(), "off")

    def test_cli_missing_never_stops_the_interrupt(self):
        os.environ["PATH"] = "/nonexistent"
        self.assertEqual(self.run_stop(), 0)
        self.assertTrue(any("hal2-cli-workqueue not found" in line for line in self.lines))
        self.assertEqual(self.argv(), [])
        self.assertEqual(interrupt.main(["done"], self.deps()), 0)
        self.assertEqual(self.mode(), "off")

    def test_a_failing_call_is_reported_not_fatal(self):
        os.environ["FAKE_WQ_FAIL"] = "1"
        self.assertEqual(self.run_stop(), 0)
        self.assertTrue(any("quiet on failed (exit 3: boom)" in line for line in self.lines))
        state = json.loads(stopall.record().read_text())
        self.assertFalse(any("workqueue quiet" in a["text"] for a in state["actions"]))
        os.environ.pop("FAKE_WQ_FAIL")
        self.assertEqual(interrupt.main(["done"], self.deps()), 0)
        self.assertEqual(self.argv(), ["quiet", "quiet on"])  # done ran no quiet off: stop never set it

    def test_dry_run_changes_nothing(self):
        self.assertEqual(self.run_stop("--dry-run"), 0)
        self.assertEqual(self.argv(), [])
        self.assertTrue(any(line.startswith("would set workqueue quiet on") for line in self.lines))
        self.assertEqual(self.run_stop(), 0)
        self.lines.clear()
        self.assertEqual(interrupt.main(["done", "--dry-run"], self.deps()), 0)
        self.assertEqual(self.mode(), "on")
        self.assertTrue(any(line.startswith("would undo set workqueue quiet on") for line in self.lines))

    def test_parse(self):
        for out, want in (("quiet: on\n", "on"), ("Quiet mode: OFF", "off"), ('{"quiet": true}', "on"),
                          ('{"quiet": "off"}', "off"), ("on", "on"), ("???", None), ("", None)):
            self.assertEqual(wq_quiet.parse(out), want, out)


if __name__ == "__main__":
    unittest.main()
