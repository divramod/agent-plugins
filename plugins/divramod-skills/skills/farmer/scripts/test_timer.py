import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer
import tick
import timer
from test_farmer import Repo


class Cron(unittest.TestCase):
    def test_the_loop_crons_minutes(self):
        self.assertEqual(timer.minutes("7-59/15 * * * *"), [7, 22, 37, 52])
        self.assertEqual(timer.minutes("4 * * * *"), [4])
        with self.assertRaises(ValueError):
            timer.minutes("0 9 * * 1")

    @unittest.skipUnless(shutil.which("plutil"), "plutil is macOS's (the gate job runs on Linux)")
    def test_the_plist_is_valid_and_runs_the_tick_at_each_minute(self):
        state = Path(tempfile.mkdtemp())
        f = state / "x.plist"
        f.write_text(timer.plist("hal2", "/w/farmer", state, "2-59/5 * * * *"))
        self.assertEqual(subprocess.run(["plutil", "-lint", str(f)], capture_output=True).returncode, 0)
        data = json.loads(subprocess.run(["plutil", "-convert", "json", "-o", "-", str(f)],
                                         capture_output=True, text=True).stdout)
        self.assertEqual(data["Label"], "local.farmer.hal2")
        self.assertEqual(data["ProgramArguments"][-4:], [str(timer.FARMER), "tick", "--repo", "/w/farmer"])
        self.assertEqual([d["Minute"] for d in data["StartCalendarInterval"]], list(range(2, 60, 5)))

    def test_the_systemd_timer_names_the_same_minutes(self):
        service, t = timer.systemd("hal2", "/w/farmer", Path("/s"), "7-59/15 * * * *")
        self.assertIn("OnCalendar=*-*-* *:07,22,37,52:00", t)
        self.assertIn("tick --repo /w/farmer", service)


class Install(Repo):
    def setUp(self):
        super().setUp()
        self.home, self.cmds = self.tmp / "home", []

        def run(cmd):
            self.cmds.append(cmd)
            return 0, ""

        for p in (mock.patch.object(timer.Path, "home", return_value=self.home),
                  mock.patch.object(timer, "run", run), mock.patch.object(timer.platform, "system",
                                                                          return_value="Darwin"),
                  mock.patch.object(farmer.shutil, "which", return_value="/bin/x")):
            p.start()
            self.addCleanup(p.stop)

    def cli(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()):
            return farmer.main([*argv, "--repo", str(self.slot)])

    def test_install_switches_to_timer_mode_remove_back(self):
        self.assertEqual(self.cli("timer", "install", "--dry-run"), 0)
        self.assertEqual((self.cmds, farmer.mode(str(self.slot))), ([], "claude"))
        self.assertEqual(self.cli("timer", "install"), 0)
        plist = self.home / "Library/LaunchAgents/local.farmer.hal2.plist"
        self.assertIn("<integer>52</integer>", plist.read_text())
        self.assertEqual(self.cmds[-1][:2], ["launchctl", "bootstrap"])
        self.assertEqual(farmer.mode(str(self.slot)), "timer")
        self.assertEqual(timer.installed(farmer.state(str(self.slot)))["cron"], "7-59/15 * * * *")
        self.assertEqual(self.cli("timer", "remove"), 0)
        self.assertFalse(plist.exists())
        self.assertEqual(farmer.mode(str(self.slot)), "claude")

    def test_a_changed_loop_cron_reinstalls(self):
        self.cli("timer", "install")
        n = len(self.cmds)
        farmer.follow_cron(str(self.slot))
        self.assertEqual(len(self.cmds), n)
        (self.slot / tick.ROLE).write_text((self.slot / tick.ROLE).read_text()
                                                 .replace('mtm: "*/15', 'mtm: "*/5'))
        with contextlib.redirect_stdout(io.StringIO()):
            farmer.follow_cron(str(self.slot))
        self.assertEqual(timer.installed(farmer.state(str(self.slot)))["cron"], "2-59/5 * * * *")


if __name__ == "__main__":
    unittest.main()
