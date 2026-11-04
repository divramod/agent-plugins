"""hal2-daemon's quiet pollers round trip (pollers_quiet.py, plan 0584 D12): stop holds `pollers` through
`hal2-cli-machine quiet hold pollers` instead of freezing hal2-daemon, done releases it, only when the interrupt held
it; without the CLI or on a failed hold hal2-daemon is frozen as before. The CLI is a fake shell script in a temp dir
that logs its argv and keeps a state file; the machine, the sessions and quiet.py are the fakes of test_interrupt."""
import json
import os
import stat
import unittest
from pathlib import Path

import freeze
import interrupt
import stopall
from test_interrupt import Base

FAKE = """#!/bin/sh
echo "$@" >> "$FAKE_QM_DIR/argv.log"
state="$FAKE_QM_DIR/held"
[ -n "$FAKE_QM_FAIL" ] && [ "$2" = "hold" ] && { echo boom >&2; exit 3; }
case "$2" in
  hold) echo yes > "$state" ;;
  release) echo no > "$state" ;;
  status) if [ "$(cat "$state")" = yes ]; then echo '{"schema":1,"holds":[{"target":"pollers"}]}';
          else echo '{"schema":1,"holds":[]}'; fi ;;
esac
exit 0
"""


class CliSys:
    """The fake machine for everything but hal2-cli-machine, which really runs (the fake script)."""

    def __init__(self, fake, cli):
        self.fake, self.cli, self.real = fake, cli, freeze.Sys()

    def run(self, cmd, timeout=60):
        return (self.real if cmd[0] == self.cli else self.fake).run(cmd, timeout)

    def __getattr__(self, name):
        return getattr(self.fake, name)


class PollersRoundTrip(Base):
    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.cli = base / "hal2-cli-machine"
        self.cli.write_text(FAKE)
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        (base / "held").write_text("no\n")
        self.base = base
        os.environ["FAKE_QM_DIR"] = str(base)
        os.environ["HAL2_CLI_MACHINE"] = str(self.cli)
        os.environ.pop("FAKE_QM_FAIL", None)
        self.sys = CliSys(self.sys, str(self.cli))

    def tearDown(self):
        for k in ("FAKE_QM_DIR", "FAKE_QM_FAIL"):
            os.environ.pop(k, None)
        super().tearDown()

    def argv(self):
        log = self.base / "argv.log"
        return log.read_text().splitlines() if log.exists() else []

    def held(self):
        return (self.base / "held").read_text().strip() == "yes"

    def test_stop_holds_the_pollers_instead_of_freezing_the_daemon_and_done_releases_them(self):
        self.assertEqual(self.run_stop("--note", "a call"), 0)
        self.assertTrue(self.held())
        self.assertEqual(self.argv(), ["quiet status --json", "quiet hold pollers --reason important interrupt: a call"])
        self.assertNotIn((600, "STOP"), self.sys.kills, "hal2-daemon is not frozen")
        state = json.loads(stopall.record().read_text())
        texts = [a["text"] for a in state["actions"]]
        self.assertEqual(texts[0], "hold hal2 pollers")
        self.assertEqual(texts[1], "stop tart VM hal2-ci-runner-macos")
        self.assertFalse(any(t.startswith("freeze hal2-daemon") for t in texts))
        self.assertEqual(state["actions"][0]["undo"], [str(self.cli), "quiet", "release", "pollers"])
        self.assertEqual(state["important_interrupt"]["pollers_quiet"], {"cli": str(self.cli), "set": True})
        row = json.loads((interrupt.root() / "log.jsonl").read_text().splitlines()[-1])
        self.assertEqual(row["counts"]["pollers"], 1)
        self.assertNotIn("daemon", row["counts"])
        self.assertEqual(interrupt.main(["done"], self.deps()), 0)
        self.assertFalse(self.held())
        self.assertEqual(self.argv()[-1], "quiet release pollers")
        undos = [line for line in self.lines if line.startswith("undo ")]
        self.assertTrue(undos[-1].startswith("undo hold hal2 pollers"), undos)

    def test_a_hold_set_before_stays(self):
        (self.base / "held").write_text("yes\n")
        self.assertEqual(self.run_stop(), 0)
        self.assertEqual(self.argv(), ["quiet status --json"])
        self.assertNotIn((600, "STOP"), self.sys.kills)
        state = json.loads(stopall.record().read_text())
        self.assertFalse(any(a["text"] == "hold hal2 pollers" for a in state["actions"]))
        self.assertEqual(interrupt.main(["done"], self.deps()), 0)
        self.assertTrue(self.held(), "done leaves the earlier hold")

    def test_a_failing_hold_freezes_the_daemon_and_is_not_fatal(self):
        os.environ["FAKE_QM_FAIL"] = "1"
        self.assertEqual(self.run_stop(), 0)
        self.assertTrue(any("hold hal2 pollers failed (exit 3: boom)" in line for line in self.lines))
        self.assertIn((600, "STOP"), self.sys.kills)
        texts = [a["text"] for a in json.loads(stopall.record().read_text())["actions"]]
        self.assertTrue(texts[0].startswith("freeze hal2-daemon 600"))

    def test_cli_missing_freezes_the_daemon(self):
        os.environ["HAL2_CLI_MACHINE"] = str(self.base / "missing")
        self.assertEqual(self.run_stop(), 0)
        self.assertTrue(any("hal2-cli-machine not found" in line for line in self.lines))
        self.assertIn((600, "STOP"), self.sys.kills)
        self.assertEqual(self.argv(), [])

    def test_dry_run_changes_nothing(self):
        self.assertEqual(self.run_stop("--dry-run"), 0)
        self.assertEqual(self.argv(), [])
        self.assertFalse(self.held())
        out = "\n".join(self.lines)
        self.assertIn("would hold hal2 pollers", out)
        self.assertNotIn("would freeze hal2-daemon", out)


if __name__ == "__main__":
    unittest.main()
