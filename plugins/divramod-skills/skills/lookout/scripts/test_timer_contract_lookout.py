"""lookout's timer answers hal2-machine's standard installer contract (hal2 plan 0581, step 6b): job `lookout-timer`,
`lookout.py timer install|enable|disable|status --json`, the shape checked against the Rust crate's fixtures through
the farmer's check, every verb over launchd and systemd with launchctl and systemctl faked (nothing real is
installed, loaded or called).
Run from the scripts folder: python3 -m unittest test_timer_contract_lookout"""

import datetime as dt
import json
import unittest

import lookout
import lookout_frame  # noqa: F401  (the farmer's scripts on the path: before the next imports)
import paths
import test_timer_lookout as base
import test_timer_standard as std
import timer
import timer_standard as ts
from unittest import mock


class Contract(base.TimerCase):
    def setUp(self):
        super().setUp()
        self.loaded, self.exit = False, None
        p = mock.patch.object(timer, "run", std.Fake.launch.__get__(self))
        p.start()
        self.addCleanup(p.stop)

    def reply(self, *verb):
        code, out, _ = self.cli("timer", *verb, "--json")
        self.assertEqual(out.count("\n"), 1, out)
        r = json.loads(out)
        self.assertEqual(ts.problems(r), [], r)
        return code, r

    def test_every_verb_over_launchd(self):
        code, r = self.reply("status")
        self.assertEqual((code, r["job"], r["state"], r["enabled"]), (3, "lookout-timer", "missing", False))
        self.assertEqual((self.reply("enable")[0], self.reply("disable")[0]), (3, 3))
        self.assertEqual({c[1] for c in self.cmds}, {"print"}, "a missing timer is only read")
        code, r = self.reply("install")
        self.assertEqual((code, r["state"], r["enabled"]), (0, "installed", True))
        self.assertIn("cron */5 * * * *", r["message"])
        state = paths.state_root()
        self.assertEqual((state / "mode").read_text(), "timer\n")
        self.exit = 78
        self.assertEqual((self.reply("status")[1]["state"], self.reply("status")[1]["last_exit"]), ("failing", 78))
        self.exit = 0
        code, r = self.reply("disable")
        self.assertEqual((code, r["state"], r["enabled"]), (0, "disabled", False))
        self.assertTrue((self.home / "Library/LaunchAgents/local.lookout.global.plist").exists())
        self.assertEqual(self.reply("enable")[1]["state"], "installed")
        self.assertEqual(self.cli("timer", "remove")[0], 0)
        self.assertEqual(self.reply("status")[0], 3)
        self.assertEqual({c[0] for c in self.cmds}, {"launchctl"})

    def test_a_stale_heartbeat_is_failing_a_fresh_one_is_not(self):
        self.reply("install")
        state = paths.state_root()
        (state / "heartbeat").write_text(dt.datetime.now().astimezone().isoformat() + "\n")
        self.assertEqual(self.reply("status")[1]["state"], "installed")
        old = (dt.datetime.now().astimezone() - dt.timedelta(minutes=30)).isoformat()
        (state / "heartbeat").write_text(old + "\n")
        code, r = self.reply("status")
        self.assertEqual((code, r["state"]), (0, "failing"))
        self.assertIn("lookout not running since", r["message"])

    def test_the_older_commands_are_as_they_were(self):
        self.assertEqual(self.cli("start")[0], 0)
        self.assertIn("local.lookout.global: loaded", self.cli("timer", "status")[1])
        self.assertEqual(self.cli("stop")[0], 0)
        self.assertIn("local.lookout.global: not loaded", self.cli("status")[1])

    def test_a_failing_launchctl_is_exit_2(self):
        with mock.patch.object(timer, "run", lambda cmd: (5, "denied") if cmd[1] == "bootstrap" else (113, "")):
            code, out, err = self.cli("timer", "install", "--json")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("denied", err)

    def test_the_windows_gap_touches_nothing(self):
        with mock.patch.object(lookout.platform, "system", return_value="Windows"):
            code, out, err = self.cli("timer", "status", "--json")
        self.assertEqual((code, out, self.cmds), (2, "", []))
        self.assertIn("no Windows path", err)

    @unittest.skipIf(std.FIXTURES is None, "the Rust crate's fixtures are not in this checkout")
    def test_the_replies_have_the_rust_fixtures_fields(self):
        self.assertEqual(list(self.reply("status")[1]), list(std.fixture("status-installed.json")))


class ContractSystemd(Contract):
    system = "Linux"

    def test_every_verb_over_launchd(self):  # the base test's name: here over a systemd user timer
        self.assertEqual(self.reply("status")[0], 3)
        self.assertEqual(self.reply("install")[1]["state"], "installed")
        self.assertTrue((self.home / ".config/systemd/user/local.lookout.global.timer").exists())
        self.assertEqual(self.reply("disable")[1]["state"], "disabled")
        self.assertEqual(self.reply("enable")[1]["state"], "installed")
        self.assertEqual({c[0] for c in self.cmds}, {"systemctl"})

    test_the_older_commands_are_as_they_were = None
    test_a_failing_launchctl_is_exit_2 = None
    test_the_windows_gap_touches_nothing = None


if __name__ == "__main__":
    unittest.main()
