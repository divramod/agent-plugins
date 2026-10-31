"""Hal2 plan 0490 step 10, learning L58 (2026-10-20 14:16Z): `tollman.py order` hung 10 min on `git ls-remote` (the
ssh link to GitHub stalled) and failed by the 600 s timeout. carrier.git runs through the farmer's bounded.run (plan
0480's L63): a call to origin gets the network limit, an ssh keepalive and one more try only after a timeout; a
healthy call runs once, a local call keeps the carrier's limit, and a timeout is an exit code, never an exception.
No real git: bounded.once is replaced."""

import os
import subprocess
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import bounded
import carrier


class Calls:
    """bounded.once's stand-in: each call recorded (argv, limit, env), the first `stalls` calls time out."""

    def __init__(self, stalls: int = 0):
        self.calls, self.stalls = [], stalls

    def __call__(self, argv, cwd, limit, env, *rest):
        self.calls.append((argv, limit, env))
        if len(self.calls) <= self.stalls:
            raise subprocess.TimeoutExpired(argv, limit)
        return subprocess.CompletedProcess(argv, 0, "abc123\trefs/heads/x\n", "")


class CarrierGit(unittest.TestCase):
    def run_git(self, stalls: int, *args: str, env: dict | None = None):
        calls = Calls(stalls)
        with mock.patch.object(bounded, "once", calls), mock.patch.dict(os.environ, env or {}, clear=False):
            if env is None:
                os.environ.pop("GIT_SSH_COMMAND", None)
                os.environ.pop("GIT_SSH", None)
            return carrier.git("/tmp", *args), calls.calls

    def test_the_stalled_ls_remote_of_l58_is_tried_once_more_and_never_waits_600_s(self):
        (code, text), calls = self.run_git(1, "ls-remote", "origin", "refs/heads/x")
        self.assertEqual((code, len(calls)), (0, 2), text)
        for _, limit, env in calls:
            self.assertEqual(limit, bounded.NETWORK_GIT)
            self.assertEqual(env["GIT_SSH_COMMAND"], carrier.KEEPALIVE)
            self.assertIn("ServerAliveInterval=15", env["GIT_SSH_COMMAND"])

    def test_a_healthy_push_runs_once(self):
        (code, _), calls = self.run_git(0, "push", "-q", "origin", "HEAD:refs/heads/x")
        self.assertEqual((code, len(calls)), (0, 1), "the retry never lengthens a healthy push (D9)")

    def test_two_timeouts_are_exit_124_never_an_exception(self):
        (code, text), calls = self.run_git(5, "fetch", "-q", "origin", "main")
        self.assertEqual((code, len(calls)), (carrier.TIMED_OUT, 2))
        self.assertIn(f"timed out after {bounded.NETWORK_GIT} s", text)

    def test_a_local_merge_keeps_its_limit_no_retry_and_no_ssh(self):
        (code, text), calls = self.run_git(1, "merge", "-q", "x")
        self.assertEqual((code, len(calls)), (carrier.TIMED_OUT, 1), text)
        self.assertEqual(calls[0][1], carrier.LOCAL_LIMIT)
        self.assertIsNone(calls[0][2])

    def test_the_environment_s_own_ssh_command_is_kept(self):
        (_, _), calls = self.run_git(0, "fetch", "origin", env={"GIT_SSH_COMMAND": "ssh -i k"})
        self.assertEqual(calls[0][2]["GIT_SSH_COMMAND"], "ssh -i k")


if __name__ == "__main__":
    unittest.main()
