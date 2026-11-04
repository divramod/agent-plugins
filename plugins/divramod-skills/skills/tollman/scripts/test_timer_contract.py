"""The tollman's timer answers hal2-machine's standard installer contract (hal2 plan 0581, step 6b): job
`tollman-timer`, the reply's shape checked against the Rust crate's fixtures through the farmer's check, every verb
over launchd and systemd with the system tools faked (no real timer is installed, loaded or called).
Run from the scripts folder: python3 -m unittest test_timer_contract"""

import json
import unittest
from unittest import mock

import test_tollman  # first: its frame puts the farmer's scripts on the path
import test_timer_standard as std
import timer
import timer_standard as ts


class Contract(test_tollman.Field):
    system = "Darwin"

    def setUp(self):
        super().setUp()
        self.loaded, self.exit = False, None
        for p in (mock.patch.object(timer, "run", self.launch),
                  mock.patch.object(timer.platform, "system", return_value=self.system)):
            p.start()
            self.addCleanup(p.stop)

    launch = std.Fake.launch

    def reply(self, *verb):
        code, out = self.call("timer", *verb, "--json")
        self.assertEqual(out.count("\n"), 1, out)
        r = json.loads(out)
        self.assertEqual(ts.problems(r), [], r)
        return code, r

    def test_every_verb_over_launchd(self):
        code, r = self.reply("status")
        self.assertEqual((code, r["job"], r["state"], r["enabled"]), (3, "tollman-timer", "missing", False))
        self.assertEqual(self.reply("enable")[0], 3)
        code, r = self.reply("install")
        self.assertEqual((code, r["state"], r["enabled"]), (0, "installed", True))
        self.assertIn("local.tollman.hal2", r["message"])
        self.assertEqual((self.wm_state / "mode").read_text(), "timer\n")
        self.exit = 1
        self.assertEqual(self.reply("status")[1]["state"], "failing")
        self.exit = 0
        code, r = self.reply("disable")
        self.assertEqual((code, r["state"], r["enabled"]), (0, "disabled", False))
        self.assertEqual((self.wm_state / "mode").read_text(), "claude\n")
        self.assertEqual(self.reply("enable")[1]["state"], "installed")
        self.assertEqual((self.wm_state / "mode").read_text(), "timer\n")
        self.assertEqual(self.call("timer", "remove"), (0, "remove: mode claude\n"))
        self.assertEqual(self.reply("status")[0], 3)
        self.assertEqual({c[0] for c in self.cmds}, {"launchctl"})

    def test_a_refused_install_is_exit_1_never_the_start_checks_3_or_4(self):
        (self.wm / "roles/tollman/ROLE.md").unlink()
        code, text = self.call("timer", "install", "--json")  # call() gives stdout, else stderr
        self.assertEqual(code, 1)
        self.assertIn("nothing is opted in", text)

    def test_the_farmers_timer_is_another_job(self):
        self.reply("install")
        self.assertEqual(self.reply("status")[1]["job"], "tollman-timer")
        self.assertFalse((self.tmp / "Library/LaunchAgents/local.farmer.hal2.plist").exists())

    @unittest.skipIf(std.FIXTURES is None, "the Rust crate's fixtures are not in this checkout")
    def test_the_rust_fixture_has_this_jobs_fields(self):
        self.assertEqual(list(std.fixture("status-installed.json")), list(ts.FIELDS))
        self.assertEqual(std.fixture("status-installed.json")["job"], "tollman-timer")


class ContractSystemd(Contract):
    system = "Linux"

    def test_every_verb_over_launchd(self):  # the base test's name: here over a systemd user timer
        self.assertEqual(self.reply("status")[0], 3)
        self.assertEqual(self.reply("install")[1]["state"], "installed")
        self.assertTrue((self.tmp / ".config/systemd/user/local.tollman.hal2.timer").exists())
        self.assertEqual(self.reply("disable")[1]["state"], "disabled")
        self.assertEqual(self.reply("enable")[1]["state"], "installed")
        self.assertEqual({c[0] for c in self.cmds}, {"systemctl"})

    test_a_refused_install_is_exit_1_never_the_start_checks_3_or_4 = None
    test_the_farmers_timer_is_another_job = None


if __name__ == "__main__":
    unittest.main()
