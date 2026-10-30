"""bounded.run: a time limit and one retry on every git/gh call of a tick (hal2 plan 0480 step 06.01, L63).

Fake `git`, `gh` and `hal2-cli-git` programs sit first on PATH in a scratch folder; every limit is a tiny one, so no
test sleeps for real. A stalled fake leaves a `sleep` child behind that the test proves dead."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bounded  # noqa: E402

TINY = 0.4
STALL = 'echo x >> "$COUNT"\nsleep 300 &\necho $! > "$CHILD"\nwait\n'


class Fakes(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "bin").mkdir()
        env = {"PATH": f"{self.dir / 'bin'}:/usr/bin:/bin", "COUNT": str(self.dir / "count"),
               "CHILD": str(self.dir / "child"), "SEEN": str(self.dir / "env")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for k in ("GIT_SSH_COMMAND", "GIT_SSH", "GIT_HTTP_LOW_SPEED_TIME"):
            os.environ.pop(k, None)

    def fake(self, name, body):
        f = self.dir / "bin" / name
        f.write_text(f"#!/bin/sh\n{body}")
        f.chmod(0o755)

    def calls(self):
        f = self.dir / "count"
        return len(f.read_text().split()) if f.exists() else 0


class Bounded(Fakes):
    def test_a_stalled_git_ends_within_the_limit_is_retried_once_and_leaves_no_child(self):
        self.fake("git", STALL)
        t0 = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            bounded.run(["git", "rev-parse", "HEAD"], timeout=TINY)
        self.assertLess(time.monotonic() - t0, 10, "two limits plus the kills, no 300 s sleep")
        self.assertEqual(self.calls(), 2, "one try and exactly one retry")
        child = int((self.dir / "child").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)  # the group was killed, not only the shell

    def test_a_real_error_exit_is_not_retried(self):
        self.fake("git", 'echo x >> "$COUNT"\necho "fatal: not a git repository" >&2\nexit 128\n')
        p = bounded.run(["git", "status"], timeout=TINY)
        self.assertEqual((p.returncode, self.calls()), (128, 1))
        self.assertIn("not a git repository", p.stderr)

    def test_a_transient_network_fault_is_retried_once_and_the_second_answer_returns(self):
        self.fake("git", 'echo x >> "$COUNT"\nif [ "$(wc -w < "$COUNT")" -lt 2 ]; then\n'
                         '  echo "fatal: unable to access \'https://github.com/x/y/\': Could not resolve host: github.com" >&2\n'
                         '  exit 128\nfi\necho fine\n')
        p = bounded.run(["git", "fetch", "origin"], timeout=TINY)
        self.assertEqual((p.returncode, p.stdout.strip(), self.calls()), (0, "fine", 2))

    def test_a_fault_that_stays_is_retried_once_not_forever(self):
        self.fake("gh", 'echo x >> "$COUNT"\necho "dial tcp: i/o timeout" >&2\nexit 1\n')
        p = bounded.run(["gh", "run", "list"], timeout=TINY)
        self.assertEqual((p.returncode, self.calls()), (1, 2))

    def test_each_transient_wording_counts(self):
        for text in ("ssh: connect to host github.com port 22: Operation timed out", "Connection timed out",
                     "error: RPC failed; curl 56", "fatal: early EOF", "HTTP 502: Bad Gateway", "Connection reset by peer"):
            with self.subTest(text):
                p = subprocess.CompletedProcess(["git"], 1, "", text)
                self.assertTrue(bounded.transient(p, ["git", "fetch"]))
        for text in ("fatal: couldn't find remote ref x", "error: pathspec 'x' did not match", "bad revision 'x'"):
            with self.subTest(text):
                p = subprocess.CompletedProcess(["git"], 1, "", text)
                self.assertFalse(bounded.transient(p, ["git", "fetch"]))

    def test_a_call_that_changes_the_checkout_is_not_retried_on_a_timeout(self):
        self.fake("git", STALL)
        with self.assertRaises(subprocess.TimeoutExpired):
            bounded.run(["git", "-C", str(self.dir), "merge", "origin/main"], timeout=TINY)
        self.assertEqual(self.calls(), 1)

    def test_retry_false_asks_for_none(self):
        self.fake("gh", STALL)
        with self.assertRaises(subprocess.TimeoutExpired):
            bounded.run(["gh", "pr", "list"], timeout=TINY, retry=False)
        self.assertEqual(self.calls(), 1)

    def test_the_happy_path_runs_once_and_returns_text(self):
        self.fake("git", 'echo x >> "$COUNT"\necho out\necho err >&2\n')
        p = bounded.run(["git", "log"], cwd=str(self.dir))
        self.assertEqual((p.returncode, p.stdout, p.stderr, self.calls()), (0, "out\n", "err\n", 1))

    def test_a_missing_program_is_an_oserror_and_input_reaches_stdin(self):
        with self.assertRaises(OSError):
            bounded.run(["no-such-program-hal2"], timeout=TINY)
        self.fake("git", "cat\n")
        self.assertEqual(bounded.run(["git", "hash-object"], input="abc").stdout, "abc")

    def test_default_limits_follow_the_command(self):
        lim = bounded.limit_for
        self.assertEqual(lim(["git", "-C", "/x", "status"]), bounded.LOCAL_GIT)
        self.assertEqual(lim(["git", "fetch", "--quiet", "origin"]), bounded.NETWORK_GIT)
        self.assertEqual(lim(["/usr/bin/git", "-c", "a=b", "push"]), bounded.NETWORK_GIT)
        self.assertEqual(lim(["gh", "api", "x"]), bounded.GH)
        self.assertEqual(lim(["hal2-cli-git", "worktree", "merge-from-main", "--json"]), bounded.LONG)
        self.assertEqual(lim(["hal2-cli-git", "worktree", "queue", "order"]), bounded.HAL)
        self.assertGreater(bounded.LONG, bounded.NETWORK_GIT)
        self.assertGreater(bounded.NETWORK_GIT, bounded.LOCAL_GIT)

    def test_a_network_git_gets_the_low_speed_and_keepalive_settings_a_local_one_does_not(self):
        self.fake("git", 'env > "$SEEN"\n')
        bounded.run(["git", "fetch", "origin"])
        seen = (self.dir / "env").read_text()
        for want in ("GIT_HTTP_LOW_SPEED_LIMIT=1000", "GIT_HTTP_LOW_SPEED_TIME=60", "ServerAliveInterval=15",
                     "ServerAliveCountMax=3", "GIT_TERMINAL_PROMPT=0"):
            self.assertIn(want, seen)
        (self.dir / "env").unlink()
        bounded.run(["git", "status"])
        self.assertNotIn("GIT_HTTP_LOW_SPEED_TIME", (self.dir / "env").read_text())

    def test_the_callers_own_ssh_command_stays(self):
        self.fake("git", 'env > "$SEEN"\n')
        with mock.patch.dict(os.environ, {"GIT_SSH_COMMAND": "ssh -i mine"}):
            bounded.run(["git", "push"])
        seen = (self.dir / "env").read_text()
        self.assertIn("GIT_SSH_COMMAND=ssh -i mine", seen)
        self.assertNotIn("ServerAlive", seen)


class Sites(Fakes):
    """The tick's own call sites: a stalled program ends within the (tiny) default limit, is tried twice and the
    caller sees what it saw before (an empty answer, 127), not a hang."""

    def stalled(self, name, limit_name, *call):
        self.fake(name, STALL)
        with mock.patch.object(bounded, limit_name, TINY):
            t0 = time.monotonic()
            result = call[0](*call[1:])
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(self.calls(), 2, f"{name}: one try and one retry")
        return result

    def test_the_readers_of_github_and_git_end_within_their_limits(self):
        import ci_scan
        import mtm_ci
        import mtm_scan
        self.assertEqual(self.stalled("gh", "GH", mtm_scan.run, ["gh", "run", "list"], str(self.dir)), "")
        (self.dir / "count").unlink()
        self.assertEqual(self.stalled("gh", "GH", ci_scan.run, ["gh", "run", "list"], str(self.dir)), "")
        (self.dir / "count").unlink()
        self.assertEqual(self.stalled("git", "LOCAL_GIT", mtm_ci._git, ["git", "ls-tree", "HEAD"], str(self.dir)), "")

    def test_the_frames_fetch_and_merge_from_main_end_within_their_limits(self):
        import tick
        code, text = self.stalled("git", "NETWORK_GIT", tick.sh, ["git", "fetch", "--quiet", "origin", "main"], str(self.dir))
        self.assertEqual(code, 127)
        self.assertIn("timed out", text)
        (self.dir / "count").unlink()
        self.assertEqual(self.stalled("hal2-cli-git", "LONG", tick.sh, tick.MFM, str(self.dir))[0], 127)

    def test_a_local_git_of_the_ticks_helpers_gives_an_empty_answer(self):
        import tick
        self.assertEqual(self.stalled("git", "LOCAL_GIT", tick.git, str(self.dir), "rev-parse", "HEAD"), "")


if __name__ == "__main__":
    unittest.main()
