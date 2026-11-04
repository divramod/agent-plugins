"""quiet_probe.py and quiet.py's scan on fakes: every call under a timeout, one scan, batched lsof, simctl only when
a simulator runs (plan 0585 D12)."""
import os
import signal
import subprocess
import tempfile
import unittest
from unittest import mock

import quiet
import quiet_probe
import stopall

TABLE = {1: {"pid": 1, "ppid": 0, "cpu": 0, "rss_mb": 1, "stat": "S", "cmd": "/sbin/launchd"},
         10: {"pid": 10, "ppid": 1, "cpu": 1, "rss_mb": 1, "stat": "S", "cmd": "/usr/local/bin/claude --x"},
         11: {"pid": 11, "ppid": 1, "cpu": 1, "rss_mb": 1, "stat": "S", "cmd": "codex"}}


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["STOP_ALL_AGENT_WORK_ROOT"] = self.tmp.name

    def tearDown(self):
        del os.environ["STOP_ALL_AGENT_WORK_ROOT"]
        self.tmp.cleanup()

    def hang(self, kill_error=None):
        """A fake child that never ends: the first communicate times out, the one after the kill returns. No real
        process, no clock: the test counts the calls, it never measures time (rule fast-tests)."""
        child = mock.Mock(pid=4242, returncode=None)
        child.communicate.side_effect = [subprocess.TimeoutExpired("x", 0.5), ("", None)]
        popen = mock.patch.object(quiet_probe.subprocess, "Popen", return_value=child)
        killpg = mock.patch.object(quiet_probe.os, "killpg", side_effect=kill_error)
        return child, popen, killpg

    def test_a_hanging_action_times_out_and_its_child_is_killed(self):
        child, popen, killpg = self.hang()
        with popen as p, killpg as k:
            self.assertIsNone(quiet_probe.run_step(["sh", "-c", "sleep 30 & sleep 30"], timeout=0.5))
        self.assertTrue(p.call_args.kwargs["start_new_session"])
        self.assertEqual(child.communicate.call_args_list[0].kwargs, {"timeout": 0.5})
        k.assert_called_once_with(4242, signal.SIGKILL)
        self.assertEqual(child.communicate.call_count, 2)

    def test_a_hanging_probe_gives_nothing(self):
        child, popen, killpg = self.hang()
        with popen, killpg as k:
            self.assertEqual(quiet_probe.run(["sleep", "30"], timeout=0.5), "")
        k.assert_called_once_with(4242, signal.SIGKILL)

    def test_a_child_whose_group_is_gone_is_killed_alone(self):
        child, popen, killpg = self.hang(ProcessLookupError())
        with popen, killpg:
            self.assertIsNone(quiet_probe.run_step(["sleep", "30"], timeout=0.5))
        child.kill.assert_called_once_with()

    def test_action_results(self):
        self.assertTrue(quiet_probe.run_step(["true"]))
        self.assertFalse(quiet_probe.run_step(["false"]))
        self.assertFalse(quiet_probe.run_step(["/no/such/program"]))
        self.assertEqual(quiet_probe.run(["/no/such/program"]), "")

    def test_perform_reports_a_timeout_not_a_crash(self):
        with mock.patch.object(quiet, "run_step", return_value=None):
            self.assertIsNone(quiet.perform(["docker", "pause", "x"]))
        self.assertIn("timed out after", quiet.failed(None))
        self.assertEqual(quiet.failed(False), "  (failed)")
        self.assertEqual(quiet.failed(True), "")

    def test_apply_prints_a_timed_out_action_and_goes_on(self):
        rows = [{"kind": "docker", "id": "a", "what": "container a"}, {"kind": "docker", "id": "b", "what": "container b"}]
        results = iter([None, True])
        with mock.patch.object(quiet, "perform", side_effect=lambda s: next(results)), \
                mock.patch("builtins.print") as out:
            quiet.apply([], False, False, [], rows, TABLE)
        lines = [c.args[0] for c in out.call_args_list]
        self.assertTrue(lines[0].endswith(f"(failed: timed out after {quiet_probe.ACTION}s)"))
        self.assertEqual([a["text"] for a in stopall.actions()], ["pause container b"])

    def test_the_cwds_of_all_agents_come_from_one_lsof(self):
        out = "p10\nfcwd\nn/w/hal2/07\np11\nfcwd\nn/w/hal2/08\n"
        with mock.patch.object(quiet_probe, "run", return_value=out) as run:
            self.assertEqual(quiet_probe.cwds([10, 11, 12]), {10: "/w/hal2/07", 11: "/w/hal2/08"})
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][:4], ["lsof", "-a", "-p", "10,11,12"])
        self.assertEqual(quiet_probe.cwds([]), {})

    def test_scan_with_a_table_does_not_scan_the_processes_again(self):
        with mock.patch.object(quiet, "procs", side_effect=AssertionError("second ps")), \
                mock.patch.object(quiet, "cwds", return_value={10: "/w/keep"}) as cwds, \
                mock.patch.object(quiet, "ollama_running", return_value=False), \
                mock.patch.object(quiet, "timer_agents", return_value=[]), \
                mock.patch("shutil.which", return_value=None):
            self.assertEqual(quiet.scan(["/w/keep"], False, TABLE), [])
        self.assertEqual(sorted(cwds.call_args.args[0]), [10, 11])

    def test_simctl_is_asked_only_when_a_simulator_runs(self):
        listing = "== Booted ==\n    iPhone 15 (0123456789ABCDEF0123456789ABCDEF0123) (Booted)\n"
        with mock.patch.object(quiet_probe, "run", return_value=listing) as run:
            self.assertEqual(quiet_probe.simulator_rows(TABLE), [])
            run.assert_not_called()
            sim = {**TABLE, 50: {**TABLE[10], "pid": 50, "cmd": "/Lib/CoreSimulator/launchd_sim /data"}}
            rows = quiet_probe.simulator_rows(sim)
        self.assertEqual(run.call_args.args[1], quiet_probe.SIMCTL)
        self.assertEqual(rows, [{"kind": "simulator", "udid": "0123456789ABCDEF0123456789ABCDEF0123",
                                 "what": "simulator iPhone 15"}])


if __name__ == "__main__":
    unittest.main()
