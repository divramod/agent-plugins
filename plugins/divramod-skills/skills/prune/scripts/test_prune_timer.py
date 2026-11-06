"""The prune timer (hal2 plan 0695 step 14, gap 03): the tick, its alarms, the round under launchd's bare PATH and the
plist's installer, all in a scratch folder with fake tools and a fake clock; nothing touches the live farm or launchd."""

import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

import farmer_frame  # noqa: F401
import prune_timer as pt
import timer_state as ts

BARE = "/usr/bin:/bin:/usr/sbin:/sbin"  # launchd's PATH: the login shell's never reaches a job
HERE = Path(pt.__file__).resolve()


class Scratch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo = self.root / "farm"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.state = self.root / "state"
        self.state.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.alarms, self.starts = [], []

    def alarm(self, case, reason, repo):
        self.alarms.append(case)

    def start(self, repo, folder, rid):
        self.starts.append(rid)
        return os.getpid()  # alive: this test process

    def tick(self, now, **kw):
        return pt.tick(str(self.repo), self.state, now, start=self.start, alarm=self.alarm, **kw)

    def finish(self, rc, at):
        state = ts.load(self.state)
        state["round"].update(ended=at, rc=rc)
        ts.save(self.state, state)

    def fake(self, name, body):
        f = self.bin / name
        f.write_text(f"#!/bin/sh\n{body}\n")
        f.chmod(f.stat().st_mode | stat.S_IXUSR)


class TickTest(Scratch):
    def test_a_round_starts_once_then_waits_for_the_interval(self):
        self.assertEqual(self.tick(10_000), "started")
        self.assertEqual(self.tick(10_300), "running")  # a second tick never starts a second round
        self.finish(0, 10_400)
        self.assertEqual(self.tick(10_500), "waiting")
        self.assertEqual(self.tick(10_000 + pt.INTERVAL), "started")
        self.assertEqual(len(self.starts), 2)
        self.assertEqual(self.alarms, [])

    def test_a_round_over_n_minutes_alarms_once_with_a_fake_clock(self):
        self.tick(0)
        self.tick(29 * 60)
        self.assertEqual(self.alarms, [])
        self.tick(31 * 60)
        self.tick(35 * 60)
        self.tick(50 * 60)
        self.assertEqual(self.alarms, ["prune-long"])
        self.finish(0, 55 * 60)
        self.assertEqual(self.tick(56 * 60), "started")  # the next round is a new one: a new alarm if it is long too
        self.assertEqual(self.alarms, ["prune-long"])
        self.tick(56 * 60 + 31 * 60)
        self.assertEqual(self.alarms, ["prune-long", "prune-long"])

    def test_the_limit_is_a_setting(self):
        self.tick(0, long_min=5)
        self.tick(6 * 60, long_min=5)
        self.assertEqual(self.alarms, ["prune-long"])

    def test_a_non_zero_round_alarms_once_per_incident(self):
        self.tick(0)
        self.finish(1, 100)
        self.tick(200)
        self.tick(300)
        self.assertEqual(self.alarms, ["prune-failed"])
        self.assertEqual(self.tick(pt.INTERVAL), "started")  # retried, still red: the same incident, no second alarm
        self.finish(1, pt.INTERVAL + 50)
        self.tick(pt.INTERVAL + 100)
        self.assertEqual(self.alarms, ["prune-failed"])
        self.assertEqual(self.tick(2 * pt.INTERVAL + 100), "started")
        self.finish(0, 2 * pt.INTERVAL + 150)  # a passed round closes the incident
        self.tick(2 * pt.INTERVAL + 200)
        self.assertEqual(self.tick(3 * pt.INTERVAL + 200), "started")
        self.finish(2, 3 * pt.INTERVAL + 250)
        self.tick(3 * pt.INTERVAL + 300)
        self.assertEqual(self.alarms, ["prune-failed", "prune-failed"])

    def test_a_killed_round_is_red(self):
        self.start = lambda repo, folder, rid: 2**22 + 12345  # no such process
        self.tick(0)
        self.tick(100)
        self.assertEqual(self.alarms, ["prune-failed"])
        self.assertEqual(ts.load(self.state)["round"]["rc"], -1)

    def test_the_alarm_names_the_failed_field_from_the_round_log(self):
        (self.state / pt.LOG).write_text("01  muck-out  failure  0 B  x\nfailed: 01\nprune: 0 actions\n")
        self.assertIn("failed: 01", pt.cause(self.state))


class RoundUnderLaunchdPath(Scratch):
    def run_round(self, path, rid=7):
        state = {"label": "x", "round": {"id": rid, "pid": 0, "started": 1.0, "ended": None, "rc": None}, "seen": {}}
        ts.save(self.state, state)
        argv = [sys.executable, str(HERE), "round", "--repo", str(self.repo), "--state", str(self.state), "--id", str(rid)]
        env = {"PATH": path, "HOME": str(self.root)}
        return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60).returncode

    def test_the_bare_path_alone_does_not_find_the_tools_and_the_round_says_so(self):
        self.assertEqual(self.run_round(BARE), 127)
        self.assertIn("hal2-cli-runs", (self.state / pt.LOG).read_text())
        self.assertEqual(ts.load(self.state)["round"]["rc"], 127)

    def test_the_installed_path_finds_them_under_the_bare_launchd_path(self):
        self.fake("hal2-cli-runs", f'echo "$@" > {self.root}/runs.args; exit 0')
        self.fake("git", "exit 0")
        self.fake("python3", "exit 0")
        agents = self.root / "agents"
        args = types.SimpleNamespace(dry_run=False, load=False, long_minutes=30, launch_agents=str(agents))
        which = lambda t: str(self.bin / t) if (self.bin / t).exists() else None  # noqa: E731
        self.assertEqual(pt.install(str(self.repo), self.state, args, which=which), 0)
        data = plistlib.loads(next(agents.glob("local.farmer.prune.*.plist")).read_bytes())
        path = data["EnvironmentVariables"]["PATH"]
        self.assertTrue(path.startswith(str(self.bin)))
        self.assertTrue(path.endswith(BARE))  # explicit, no login shell
        self.assertNotIn("-lc", data["ProgramArguments"])
        self.assertEqual(self.run_round(path), 0)
        self.assertIn("exec --workflow prune --", (self.root / "runs.args").read_text())
        self.assertEqual(ts.load(self.state)["round"]["rc"], 0)

    def test_a_red_round_writes_its_exit_and_the_status_says_red(self):
        self.fake("hal2-cli-runs", "echo 'failed: 01'; exit 1")
        self.assertEqual(self.run_round(f"{self.bin}:{BARE}"), 1)
        self.assertIn("failed: 01", (self.state / pt.LOG).read_text())
        self.assertIn("RED", ts.line(self.state))


class InstallTest(Scratch):
    def test_dry_run_writes_nothing_and_a_missing_tool_is_refused(self):
        agents = self.root / "agents"
        args = types.SimpleNamespace(dry_run=True, load=False, long_minutes=30, launch_agents=str(agents))
        self.assertEqual(pt.install(str(self.repo), self.state, args, which=lambda t: f"/x/{t}"), 0)
        self.assertFalse(agents.exists())
        self.assertEqual(pt.install(str(self.repo), self.state, args, which=lambda t: None), 2)

    def test_the_timer_line_names_a_dead_timer(self):
        self.assertIn("no state", ts.line(self.state))
        self.tick(1_000)
        self.assertIn("round running", ts.line(self.state, 1_100))
        self.assertIn("DEAD", ts.line(self.state, 1_000 + ts.DEAD_AFTER + 60))


if __name__ == "__main__":
    unittest.main()
