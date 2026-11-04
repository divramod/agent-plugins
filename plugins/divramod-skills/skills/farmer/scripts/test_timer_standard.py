"""The farmer's timer answers hal2-machine's standard installer contract (hal2 plan 0581, step 6b): the reply's shape
against the Rust crate's fixtures (cross-unit-formats-have-a-schema), then every verb over timer.py with the system
tools faked: launchctl and systemctl are a small state machine, nothing real is installed, loaded or called.
Run from the scripts folder: python3 -m unittest test_timer_standard"""

import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest import mock

import farmer
import role_cli
import roles
import timer
import timer_standard as ts
from test_farmer import Repo

FIXTURES = next((p / "code/rust/libs/hal2-machine/tests/fixtures/installer" for p in Path(__file__).resolve().parents
                 if (p / "code/rust/libs/hal2-machine/tests/fixtures/installer").is_dir()), None)


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


@unittest.skipIf(FIXTURES is None, "the Rust crate's fixtures are not in this checkout")
class Shape(unittest.TestCase):
    """The reply cannot drift from hal2-machine's InstallerReply: its fixtures pass our check, its refusals fail it."""

    def test_the_rust_replies_pass_the_check(self):
        for name in ("status-installed.json", "status-failing.json", "install-crontab.json"):
            self.assertEqual(ts.problems(fixture(name)), [], name)

    def test_the_rust_refusals_fail_the_check(self):
        self.assertTrue(ts.problems(fixture("no-schema.json")))
        self.assertTrue(ts.problems(fixture("schema-2.json")))

    def test_the_fields_are_the_fixtures_in_order(self):
        self.assertEqual(list(fixture("status-installed.json")), list(ts.FIELDS))
        self.assertEqual(ts.SCHEMA, fixture("status-installed.json")["schema"])
        self.assertEqual({fixture(n)["state"] for n in ("status-installed.json", "status-failing.json")},
                         {"installed", "failing"})

    def test_the_check_catches_a_drift(self):
        good = fixture("status-installed.json")
        for bad in ({**good, "state": "running"}, {**good, "enabled": 1}, {**good, "last_exit": "0"},
                    {**good, "last_run": "yesterday"}, {**good, "extra": 1}, {k: v for k, v in good.items()
                                                                              if k != "message"}):
            self.assertTrue(ts.problems(bad), bad)


class Fake:
    """launchctl and systemctl as a state machine over the patched timer.run."""

    system = "Darwin"

    def setUp(self):
        super().setUp()
        self.home, self.cmds, self.loaded, self.exit = self.tmp / "home", [], False, None
        for p in (mock.patch.object(timer.Path, "home", return_value=self.home),
                  mock.patch.object(timer, "run", self.launch), mock.patch.object(timer.platform, "system",
                                                                          return_value=self.system),
                  mock.patch.object(role_cli.shutil, "which", return_value="/bin/x")):
            p.start()
            self.addCleanup(p.stop)

    def launch(self, cmd):
        self.cmds.append(cmd)
        tool, verb = cmd[0], cmd[1]
        if tool == "launchctl":
            if verb == "print":
                text = "" if self.exit is None else f"state = not running\n\tlast exit code = {self.exit}\n"
                return (0, text) if self.loaded else (113, "")
            self.loaded = verb == "bootstrap"
            return 0, ""
        if verb == "--user":
            sub = cmd[2]
            if sub == "is-active":
                return (0 if self.loaded else 3), ""
            if sub in ("enable", "disable"):
                self.loaded = sub == "enable"
            if sub == "show":
                return 0, ("" if self.exit is None else
                           f"ExecMainStatus={self.exit}\nExecMainStartTimestamp=Tue 2026-11-03 08:15:00 CET\n")
        return 0, ""

    def cli(self, *argv, repo=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = self.entry([*argv, "--repo", str(repo or self.repo)])
        return code, out.getvalue()

    entry = staticmethod(farmer.main)

    @property
    def repo(self):
        return self.slot

    def reply(self, *verb):
        code, out = self.cli("timer", *verb, "--json")
        self.assertEqual(out.count("\n"), 1, out)
        r = json.loads(out)
        self.assertEqual(ts.problems(r), [], r)
        return code, r


class Verbs(Fake, Repo):
    def test_every_verb_over_launchd(self):
        code, r = self.reply("status")
        self.assertEqual((code, r["state"], r["enabled"], r["job"]), (3, "missing", False, "farmer-timer"))
        self.assertEqual(self.reply("enable")[0], 3, "nothing installed: nothing to enable")
        self.assertEqual(self.reply("disable")[0], 3)
        self.assertEqual(self.cmds, [c for c in self.cmds if c[1] == "print"], "a missing timer is only read")

        code, r = self.reply("install")
        self.assertEqual((code, r["job"], r["state"], r["enabled"], r["last_exit"]), (0, "farmer-timer", "installed",
                                                                                      True, None))
        self.assertIn("cron 7-59/15 * * * *", r["message"])
        plist = self.home / "Library/LaunchAgents/local.farmer.hal2.plist"
        self.assertTrue(plist.exists())
        self.assertEqual(farmer.mode(str(self.slot)), "timer")

        self.exit = 1
        self.assertEqual(self.reply("status")[1]["state"], "failing")
        self.assertEqual(self.reply("status")[1]["last_exit"], 1)
        self.exit = 0
        self.assertEqual(self.reply("status")[1]["state"], "installed")

        code, r = self.reply("disable")
        self.assertEqual((code, r["state"], r["enabled"]), (0, "disabled", False))
        self.assertTrue(plist.exists(), "disable keeps the files")
        self.assertEqual(farmer.mode(str(self.slot)), "claude")
        n = len(self.cmds)
        self.assertEqual(self.reply("disable")[1]["state"], "disabled")
        self.assertEqual([c[1] for c in self.cmds[n:]], ["print", "print"], "disabled again: only reads")

        code, r = self.reply("enable")
        self.assertEqual((code, r["state"], r["enabled"]), (0, "installed", True))
        self.assertEqual(farmer.mode(str(self.slot)), "timer")
        self.assertEqual(self.cmds[-2][1], "bootstrap")

        self.assertEqual(self.cli("timer", "remove")[0], 0)
        self.assertEqual(self.reply("status")[1]["state"], "missing")
        self.assertTrue({c[0] for c in self.cmds} <= {"launchctl"}, "no real tool is ever called")

    def test_the_last_run_is_the_tick_logs(self):
        self.reply("install")
        self.assertIsNone(self.reply("status")[1]["last_run"])
        log = farmer.state(str(self.slot)) / "tick.log"
        log.write_text("tick\n")
        import os
        os.utime(log, (1793693700, 1793693700))
        self.assertEqual(self.reply("status")[1]["last_run"], "2026-11-03T08:15:00Z")

    def test_unit_files_gone_while_loaded_fail(self):
        self.reply("install")
        (self.home / "Library/LaunchAgents/local.farmer.hal2.plist").unlink()
        self.assertEqual(self.reply("status")[1]["state"], "failing")

    def test_an_install_the_start_check_refuses_is_not_the_contracts_exit(self):
        """start-check's 3 and 4 mean other things there; a refused install answers 1 with the problems on stderr."""
        (self.slot / "roles/farmer/ROLE.md").unlink()
        code, out = self.cli("timer", "install", "--json")
        self.assertEqual((code, out), (1, ""))
        self.assertEqual({c[1] for c in self.cmds}, {"print"}, "only read")

    def test_the_machine_tool_names_the_yard_and_the_roles_own_field_installs(self):
        """The catalog's argv has `--repo ~/a/hal2` (the main checkout): install runs from the role's field."""
        with mock.patch.object(roles, "slot_dir", return_value=self.slot):
            code, out = self.cli("timer", "install", "--json", repo=self.main)
        self.assertEqual(code, 0, out)
        r = json.loads(out)
        self.assertEqual((r["job"], r["state"]), ("farmer-timer", "installed"))
        self.assertIn(f"<string>{self.slot.resolve()}</string>",
                      (self.home / "Library/LaunchAgents/local.farmer.hal2.plist").read_text())

    def test_a_failing_system_call_is_exit_2(self):
        with mock.patch.object(timer, "run", return_value=(1, "boom")):
            self.assertEqual(self.cli("timer", "install", "--json"), (2, ""))

    def test_the_older_commands_are_as_they_were(self):
        self.assertEqual(self.cli("timer", "install"), (0, "install: mode timer\n"))
        code, out = self.cli("timer", "status")
        self.assertEqual((code, out), (0, "local.farmer.hal2: loaded, cron 7-59/15 * * * *, mode timer\n"))
        detail = json.loads(self.cli("timer", "status", "--detail", "--json")[1])
        self.assertEqual((detail["label"], detail["loaded"], detail["mode"]), ("local.farmer.hal2", True, "timer"))
        self.assertEqual(self.cli("timer", "remove"), (0, "remove: mode claude\n"))

    def test_the_text_of_enable_and_disable(self):
        self.cli("timer", "install")
        self.assertEqual(self.cli("timer", "disable")[1].split(":")[:2], ["disable", " disabled"])
        self.assertEqual(self.cli("timer", "enable")[1].split(":")[:2], ["enable", " installed"])


class VerbsSystemd(Fake, Repo):
    system = "Linux"

    def test_every_verb_over_a_systemd_user_timer(self):
        self.assertEqual(self.reply("status")[0], 3)
        self.assertEqual(self.reply("install")[1]["state"], "installed")
        unit_dir = self.home / ".config/systemd/user"
        self.assertTrue((unit_dir / "local.farmer.hal2.timer").exists())
        self.exit = 2
        r = self.reply("status")[1]
        self.assertEqual((r["state"], r["last_exit"]), ("failing", 2))
        self.exit = None
        self.assertEqual(self.reply("disable")[1]["state"], "disabled")
        self.assertTrue((unit_dir / "local.farmer.hal2.service").exists())
        self.assertIn(["systemctl", "--user", "disable", "--now", "local.farmer.hal2.timer"], self.cmds)
        self.assertEqual(self.reply("enable")[1]["state"], "installed")
        self.assertIn(["systemctl", "--user", "enable", "--now", "local.farmer.hal2.timer"], self.cmds)
        self.assertEqual({c[0] for c in self.cmds}, {"systemctl"})


class Wiring(unittest.TestCase):
    def test_the_job_is_the_catalogs(self):
        self.assertEqual(ts.job_id(roles.FARMER), "farmer-timer")


if __name__ == "__main__":
    unittest.main()
