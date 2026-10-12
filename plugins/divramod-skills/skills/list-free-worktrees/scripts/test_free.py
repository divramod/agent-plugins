#!/usr/bin/env python3
"""Tests for free.py with fake hal2 CLIs on PATH (offline)."""
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
args, repo = sys.argv[1:], os.environ["FAKE_REPO"]
name = os.path.basename(repo)
if args[:1] == ["list"]:
    agent = lambda pane, slot, state, project=repo: {"pane_id": pane, "slot": slot, "state": state, "project": project}
    print(json.dumps([agent("%1", "01", "idle"), agent("%2", "02", "working"), agent("%3", "03", "idle"),
                      agent("%4", "04", "sleeping"), agent("%5", "05", "idle"), agent("%9", "06", "idle", "/x"), agent("%6", "07", "idle"),
                      agent("%0", "main", "idle")]))
elif args[:2] == ["worktree", "list"]:
    w = lambda n, **k: {"name": n, "path": "/wt/" + n, **k}
    print(json.dumps({"worktrees": [{"name": "main", "main": True}, w("01", main_behind=5),
        w("02"), w("03", plan="0007-x"), w("04", dirty=True, main_ahead=2), w("05"), w("06"),
        w("07", main_ahead=1)]}))
elif args[:2] == ["worktree", "queue"]:
    print(json.dumps({"queue": [{"repo": name, "slot": "05", "state": "waiting"}]}))
'''


class TestFree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.repo = t / "app"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.bin = t / "bin"
        self.bin.mkdir()
        for name in ("hal2-cli-agents", "hal2-cli-git"):
            (self.bin / name).write_text(FAKE)
            (self.bin / name).chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_free(self, *args):
        env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}", FAKE_REPO=str(self.repo.resolve()))
        r = subprocess.run([sys.executable, str(HERE / "free.py"), "--repo", str(self.repo), *args],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return {w["slot"]: w for w in json.loads(r.stdout)["worktrees"]}

    def test_only_idle_sessions_without_a_plan_or_landing_are_free(self):
        free = self.run_free()
        self.assertEqual(sorted(free), ["01"])
        self.assertEqual(free["01"]["panes"], ["%1"])

    def test_all_says_why_the_others_are_not_free(self):
        why = {s: w["why"] for s, w in self.run_free("--all").items()}
        self.assertEqual(why["02"], "the agent is working")
        self.assertEqual(why["03"], "works on 0007-x")
        self.assertEqual(why["04"], "uncommitted changes")
        self.assertEqual(why["05"], "its landing is waiting in the merge queue")
        self.assertEqual(why["06"], "no session running")
        self.assertEqual(why["07"], "1 commit not on main")
        self.assertNotIn("main", why)


if __name__ == "__main__":
    unittest.main()
