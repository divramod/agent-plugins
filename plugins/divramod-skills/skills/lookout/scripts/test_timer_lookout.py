"""Tests of lookout's timer (plan 0311 step 5): the label, the 5-minute grid, the tick's argv, the dry run, install
and remove with launchctl/systemctl faked (no real LaunchAgent or unit, no launchctl, no systemctl call).
Run from the scripts folder: python3 -m unittest test_timer_lookout"""

import contextlib
import datetime as dt
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import lookout
import lookout_frame  # noqa: F401
import paths
import roles
import timer


class TimerCase(unittest.TestCase):
    system = "Darwin"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home, self.cmds = self.tmp / "home", []
        env = {"LOOKOUT_DIR": str(self.tmp / "cfg"), "LOOKOUT_STATE_DIR": str(self.tmp / "state")}
        for p in (mock.patch.dict(os.environ, env), mock.patch.object(timer.Path, "home", return_value=self.home),
                  mock.patch.object(timer, "run", self.fake_run), mock.patch.object(timer.platform, "system",
                                                                              return_value=self.system)):
            p.start()
            self.addCleanup(p.stop)

    def fake_run(self, cmd):
        self.cmds.append(cmd)
        return 0, ""

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lookout.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class Wiring(TimerCase):
    def test_label_minutes_and_argv(self):
        self.assertEqual(timer.label(lookout.NAME, lookout.WIRING), "local.lookout.global")
        self.assertEqual(timer.minutes(lookout.CRON), list(range(0, 60, 5)))
        self.assertEqual(timer.argv("/top", lookout.WIRING),
                         [sys.executable, str(lookout.WIRING.cli), "tick", "--repo", "/top"])
        self.assertEqual(lookout.WIRING.cli.name, "lookout.py")

    def test_the_farmers_and_wagon_masters_timer_is_as_it_was(self):
        self.assertEqual(timer.label("hal2"), "local.farmer.hal2")
        with mock.patch.dict(os.environ, {"FARMER_DIR": "/f", "LOOKOUT_DIR": "/l", "PATH": "/bin"}, clear=True):
            self.assertEqual(timer.env(), {"PATH": "/bin", "FARMER_DIR": "/f"})
            self.assertEqual(timer.env(lookout.WIRING), {"PATH": "/bin", "LOOKOUT_DIR": "/l"})

    def test_the_frame_puts_the_farmer_scripts_on_the_path_and_the_daybooks_behind(self):
        self.assertIn(str(lookout_frame.FARMER), sys.path)
        self.assertTrue((lookout_frame.FARMER / "timer.py").exists())
        if str(lookout_frame.DAYBOOK) in sys.path:
            self.assertGreater(sys.path.index(str(lookout_frame.DAYBOOK)), sys.path.index(str(lookout_frame.FARMER)))

    @unittest.skipUnless(shutil.which("plutil"), "plutil is macOS's")
    def test_the_plist_is_valid_and_ticks_every_five_minutes(self):
        f = self.tmp / "x.plist"
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/xs"}):
            f.write_text(timer.plist(lookout.NAME, "/top", self.tmp, lookout.CRON, lookout.WIRING))
        self.assertEqual(subprocess.run(["plutil", "-lint", str(f)], capture_output=True).returncode, 0)
        data = json.loads(subprocess.run(["plutil", "-convert", "json", "-o", "-", str(f)],
                                         capture_output=True, text=True).stdout)
        self.assertEqual(data["Label"], "local.lookout.global")
        self.assertEqual(data["ProgramArguments"][-4:], [str(lookout.WIRING.cli), "tick", "--repo", "/top"])
        self.assertEqual([d["Minute"] for d in data["StartCalendarInterval"]], list(range(0, 60, 5)))
        self.assertEqual(data["EnvironmentVariables"]["XDG_STATE_HOME"], "/xs")


class Commands(TimerCase):
    def test_dry_run_prints_the_plist_and_installs_nothing(self):
        code, out, _ = self.cli("start", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("<string>local.lookout.global</string>", out)
        self.assertIn("<integer>55</integer>", out)
        self.assertIn(f"<string>{self.tmp / 'cfg'}</string>", out)  # the working directory: the store folder
        self.assertIn("launchctl bootstrap", out)
        self.assertEqual((self.cmds, list(self.home.glob("**/*")), (self.tmp / "state").exists()), ([], [], False))

    def test_start_writes_the_unit_loads_it_and_stop_removes_it(self):
        self.assertEqual(self.cli("start")[0], 0)
        plist = self.home / "Library/LaunchAgents/local.lookout.global.plist"
        self.assertIn("<integer>20</integer>", plist.read_text())
        self.assertEqual(self.cmds[-1][:2], ["launchctl", "bootstrap"])
        state = paths.state_root()
        self.assertEqual((state / "mode").read_text(), "timer\n")
        self.assertEqual(json.loads((state / "timer.json").read_text())["label"], "local.lookout.global")
        self.assertEqual(json.loads((state / "timer.json").read_text())["cron"], "*/5 * * * *")
        self.assertEqual(self.cli("stop")[0], 0)
        self.assertFalse(plist.exists())
        self.assertEqual(self.cmds[-1][:2], ["launchctl", "bootout"])
        self.assertFalse((state / "timer.json").exists())

    def test_a_failing_launchctl_is_reported_not_raised(self):
        def failing(cmd):
            self.cmds.append(cmd)
            return (5, "denied") if cmd[1] == "bootstrap" else (0, "")
        with mock.patch.object(timer, "run", failing):
            code, _, err = self.cli("start")
        self.assertEqual(code, 2)
        self.assertIn("denied", err)

    def test_status_reports_the_heartbeat(self):
        state = paths.state_root()
        state.mkdir(parents=True)
        now = dt.datetime(2026, 10, 14, 12, 0, tzinfo=dt.timezone.utc)
        self.assertIn("has not ticked yet", lookout.status_line(lookout.status(now)))
        (state / "heartbeat").write_text("2026-10-14T11:50:00+00:00\n")
        info = lookout.status(now)
        self.assertTrue(info["running"])
        self.assertIn("last tick 2026-10-14T11:50:00+00:00", lookout.status_line(info))
        (state / "heartbeat").write_text("2026-10-14T11:30:00+00:00\n")
        info = lookout.status(now)
        self.assertFalse(info["running"])
        self.assertIn("lookout not running since 2026-10-14T11:30:00+00:00", lookout.status_line(info))

    def test_status_cli_text_and_json(self):
        with mock.patch.object(timer, "run", lambda cmd: (113, "no such unit")):
            code, out, _ = self.cli("status")
        self.assertEqual(code, 0)
        self.assertIn("local.lookout.global: not loaded", out)
        data = json.loads(self.cli("status", "--json")[1])
        self.assertEqual((data["label"], data["loaded"], data["running"]), ("local.lookout.global", True, False))


class Linux(TimerCase):
    system = "Linux"

    def test_dry_run_prints_the_systemd_units(self):
        code, out, _ = self.cli("start", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("local.lookout.global.service", out)
        self.assertIn("OnCalendar=*-*-* *:00,05,10,15,20,25,30,35,40,45,50,55:00", out)
        self.assertIn("Persistent=false", out)
        self.assertIn("tick --repo", out)
        self.assertIn("systemctl --user enable --now local.lookout.global.timer", out)
        self.assertEqual(self.cmds, [])

    def test_start_writes_service_and_timer(self):
        self.assertEqual(self.cli("start")[0], 0)
        d = self.home / ".config/systemd/user"
        self.assertTrue((d / "local.lookout.global.service").exists())
        self.assertTrue((d / "local.lookout.global.timer").exists())
        self.assertEqual(self.cmds[-1], ["systemctl", "--user", "enable", "--now", "local.lookout.global.timer"])


class Windows(TimerCase):
    system = "Windows"

    def test_start_and_stop_say_the_gap_and_touch_nothing(self):
        for cmd in ("start", "stop"):
            with mock.patch.object(lookout.platform, "system", return_value="Windows"):
                code, out, err = self.cli(cmd)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("no Windows path", err)
        self.assertEqual((self.cmds, list(self.home.glob("**/*"))), ([], []))


if __name__ == "__main__":
    unittest.main()
