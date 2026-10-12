#!/usr/bin/env python3
"""Tests for stop.py with fake hal2 CLIs on PATH (offline: nothing is typed or killed)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:]) + "\n")
args, repo, exited = sys.argv[1:], os.environ["FAKE_REPO"], os.environ["FAKE_LOG"] + ".exited"
pid = int(os.environ["FAKE_PID"]) if os.environ.get("FAKE_PID") else None  # never a real process but the test's own
if pid:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        open(exited, "w").close()
if args[:1] == ["list"]:
    agents = [{"pane_id": "%7", "slot": "03", "kind": "claude", "state": os.environ.get("FAKE_STATE", "idle"),
               "project": repo, "pid": pid},
              {"pane_id": "%8", "slot": "04", "kind": "claude", "state": "idle", "project": repo, "pid": None},
              {"pane_id": "%9", "slot": "03", "kind": "claude", "state": "idle", "project": "/elsewhere"}]
    print(json.dumps([a for a in agents if not (os.path.exists(exited) and a["pane_id"] == "%7")]))
elif args[:1] == ["stop"]:
    hal2 = os.environ.get("FAKE_STOP", "ok")
    if hal2 == "old":
        sys.stderr.write('hal2-cli-agents: unknown command "stop"\n')
        sys.exit(2)
    if hal2 == "draft" and "--force" not in args:
        print(json.dumps({"pane": args[1], "refused": "draft: the input box holds \"my words\""}))
        sys.exit(3)
    open(exited, "w").close()
    print(json.dumps({"pane": args[1], "how": "signal"}))
elif args[:2] == ["terminal", "kill"]:
    open(exited, "w").close()
elif args[:2] == ["worktree", "queue"]:
    print(json.dumps({"queue": [{"repo": os.path.basename(repo), "slot": "04", "state": "active"}]}))
'''


class TestStop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.repo = t / "app"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "x"], check=True,
                       env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                                GIT_COMMITTER_EMAIL="t@t"))
        self.bin = t / "bin"
        self.bin.mkdir()
        for name in ("hal2-cli-agents", "hal2-cli-git"):
            (self.bin / name).write_text(FAKE)
            (self.bin / name).chmod(0o755)
        self.log = t / "log"

    def tearDown(self):
        self.tmp.cleanup()

    def run_stop(self, *args, code=0, **env):
        env = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "FAKE_LOG": str(self.log),
               "FAKE_REPO": str(self.repo.resolve()), "TMUX_PANE": "%99", **env}
        env.pop("HAL2_TERMINAL", None)
        r = subprocess.run([sys.executable, str(HERE / "stop.py"), *args, "--repo", str(self.repo)],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, code, r.stderr)
        return json.loads(r.stdout) if r.stdout else r.stderr

    def calls(self):
        return [c[1:] for c in map(json.loads, self.log.read_text().splitlines()) if c[1] != "list"]

    def test_list_shows_only_this_repositorys_sessions(self):
        self.assertEqual([a["pane_id"] for a in self.run_stop("list")], ["%7", "%8"])

    def test_an_idle_session_is_stopped_by_hal2_never_by_typing_exit(self):
        out = self.run_stop("stop", "3")
        self.assertEqual((out["stopped"], out["slot"], out["how"]), ("%7", "03", "signal"))
        self.assertIn(["stop", "%7", "--json"], self.calls())
        self.assertFalse([c for c in self.calls() if c[0] == "send"])

    def test_a_draft_hal2_refuses_is_refused_unless_forced(self):
        self.assertIn("my words", self.run_stop("stop", "03", code=3, FAKE_STOP="draft")["refused"])
        self.assertEqual(self.run_stop("stop", "03", "--force", FAKE_STOP="draft")["how"], "signal")
        self.assertIn(["stop", "%7", "--json", "--force"], self.calls())

    def test_an_older_hal2_without_stop_is_refused_and_forced_stopped_here(self):
        # Not this process's child, so it is reaped when it ends (a zombie would still look alive).
        pid = int(subprocess.run(["sh", "-c", "sleep 60 >/dev/null 2>&1 & echo $!"], capture_output=True,
                                 text=True).stdout)
        try:
            self.assertIn("no `hal2-cli-agents stop`", self.run_stop("stop", "03", code=3, FAKE_STOP="old")["refused"])
            out = self.run_stop("stop", "03", "--force", FAKE_STOP="old", FAKE_PID=str(pid))
            self.assertEqual(out["how"], "signal")
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass

    def test_a_busy_session_is_refused_unless_forced(self):
        self.assertIn("working", self.run_stop("stop", "03", code=3, FAKE_STATE="working")["refused"])
        self.assertEqual(self.run_stop("stop", "03", "--force", FAKE_STATE="working")["how"], "signal")

    def test_a_running_landing_is_refused(self):
        self.assertIn("landing is active", self.run_stop("stop", "04", code=3)["refused"])

    def test_its_own_session_is_refused_even_forced(self):
        out = self.run_stop("stop", "%7", "--force", code=3, TMUX_PANE="%7")
        self.assertIn("this is the session", out["refused"])

    def test_an_unknown_slot_fails(self):
        self.assertIn("no running agent session 05", self.run_stop("stop", "05", code=1))


if __name__ == "__main__":
    unittest.main()
