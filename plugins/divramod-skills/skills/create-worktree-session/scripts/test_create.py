#!/usr/bin/env python3
"""Tests for create.py with fake hal2 CLIs and a fake login shell on PATH (offline: no agent is started)."""
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
    f.write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:] + ["TMUX=" + os.environ.get("TMUX", "")]) + "\n")
args, repo = sys.argv[1:], os.environ["FAKE_REPO"]
name = os.path.basename(repo)
if args[:1] == ["list"]:
    print(json.dumps([{"pane_id": "%1", "slot": "01", "state": "idle", "project": repo},
                      {"pane_id": "%2", "slot": "05", "state": "ended", "project": repo}]))
elif args[:2] == ["terminal", "list"]:
    print(json.dumps([{"worktree": "/wt/" + name + "/02", "alive": True},
                      {"worktree": "/wt/" + name + "/03", "alive": False}]))
elif args[:2] == ["worktree", "list"]:
    w = lambda n, **k: {"name": n, "path": "/wt/" + n, **k}
    extra = [{"name": n, "path": os.path.join(os.environ["FAKE_WT"], n)}
             for n in os.environ.get("FAKE_EXTRA", "").split(",") if n]
    print(json.dumps({"worktrees": [{"name": "main", "main": True}, w("01"), w("02"),
        w("03", plan="0085-old"), w("04", main_ahead=3), w("05", dirty=True), w("06", main_behind=400),
        w("07")] + extra}))
elif args[:2] == ["worktree", "queue"]:
    print(json.dumps({"queue": [{"repo": name, "slot": "07", "state": "held"}]}))
elif args[:2] == ["worktree", "run"]:
    print("setup ...")
    print(json.dumps({"mode": "terminal", "pane": "t:abc", "slot": args[2], "worktree": "/wt/" + args[2]}))
'''

SHELL = '#!/bin/sh\n# a login shell without the login: runs the command it gets with -lc\nexec /bin/sh -c "$2"\n'

# hal2: create.py's free-disk check reads shutil.disk_usage; a sitecustomize on PYTHONPATH makes the subprocesses see
# FAKE_FREE_GB (default 1000) free, so the tests pass on a machine or CI runner with less than 50 GB free.
DISK = """import collections, os, shutil
_usage = collections.namedtuple("usage", "total used free")
_free = int(float(os.environ.get("FAKE_FREE_GB", "1000")) * 2**30)
shutil.disk_usage = lambda path: _usage(_free, 0, _free)
"""


class TestCreate(unittest.TestCase):
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
        (self.bin / "fakeshell").write_text(SHELL)
        (self.bin / "fakeshell").chmod(0o755)
        (self.bin / "sitecustomize.py").write_text(DISK)
        self.log = t / "log"
        self.home = t / "home"
        self.wt = self.home / ".hal" / "git" / "worktree" / "app"  # hal2's worktree base of the repo app
        self.wt.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_create(self, *args, extra="") -> dict:
        r = self.run_raw(*args, extra=extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def refused(self, *args, extra="") -> str:
        r = self.run_raw(*args, extra=extra)
        self.assertEqual(r.returncode, 1, r.stdout)
        return r.stderr

    def run_raw(self, *args, extra="") -> subprocess.CompletedProcess:
        env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}", FAKE_LOG=str(self.log),
                   FAKE_REPO=str(self.repo.resolve()), SHELL=str(self.bin / "fakeshell"), TMUX="/tmp/x,1,0",
                   FAKE_WT=str(self.wt), FAKE_EXTRA=extra, HOME=str(self.home), PYTHONPATH=str(self.bin))
        return subprocess.run([sys.executable, str(HERE / "create.py"), "--repo", str(self.repo), *args],
                              capture_output=True, text=True, env=env)

    def run_call(self):
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return next(c for c in calls if c[1:3] == ["worktree", "run"])

    def test_the_first_slot_without_session_and_without_work(self):
        out = self.run_create()
        self.assertEqual((out["slot"], out["pane"], out["attach"]), ("06", "t:abc", "hal2-cli-agents attach app/06"))
        self.assertEqual([(s["slot"], s["why"]) for s in out["skipped"]],
                         [("03", "works on 0085-old"), ("04", "3 commits not on main"), ("05", "uncommitted changes")])
        run = self.run_call()
        self.assertEqual(run[3:7], ["06", "--agent", "claude", "--detach"])
        self.assertEqual(run[-1], "TMUX=")  # started outside this tmux pane
        self.assertEqual(run[run.index("--prompt") + 1], "/mfm")

    def test_a_prompt_runs_after_mfm_unless_exact_and_flags_pass_through(self):
        self.run_create("--prompt", "/shoot 13", "--model", "m1", "--effort", "high", "--tmux")
        run = self.run_call()
        self.assertEqual(run[run.index("--effort") + 1], "high")
        self.assertEqual(run[run.index("--prompt") + 1], "Run /mfm (merge-from-main) first, then:\n\n/shoot 13")
        self.assertEqual(run[run.index("--model") + 1], "m1")
        self.assertIn("--tmux", run)
        self.log.unlink()
        self.run_create("--prompt", "the shot", "--exact")
        run = self.run_call()
        self.assertEqual(run[run.index("--prompt") + 1], "the shot")

    def test_the_report_echoes_the_model_and_effort_asked_for(self):
        out = self.run_create("--model", "opus", "--effort", "medium")
        self.assertEqual((out["model"], out["effort"]), ("opus", "medium"))
        self.log.unlink()
        out = self.run_create()
        self.assertEqual((out["model"], out["effort"]), (None, None))  # the agent's own default

    def test_from_starts_the_search_at_the_slot(self):
        out = self.run_create("--from", "30")
        self.assertEqual((out["slot"], out["skipped"]), ("30", []))
        self.assertIn("--from needs a slot from 01 to 99", self.refused("--from", "0"))

    def test_a_reused_clean_slot_from_30_is_taken(self):
        out = self.run_create("--from", "30", "--min-free-gb", "999999999", extra="30")
        self.assertEqual(out["slot"], "30")  # an existing worktree needs no free disk

    def test_a_new_worktree_needs_free_disk(self):
        error = self.refused("--from", "30", "--min-free-gb", "999999999")

        self.assertIn("a new worktree needs 999999999 (--min-free-gb)", error)
        self.assertFalse(self.log.exists() and "run" in self.log.read_text())

    def test_the_subservant_flags_are_gone(self):
        # Skills plan 0016 (D12): a plan's steps run in subagents; no slot is marked plans/LEAD any more.
        for flag in ("--lead", "--base"):
            error = self.refused("--from", "30", flag, "x")
            self.assertIn(f"{flag} is gone", error)
        self.assertFalse(self.log.exists() and "run" in self.log.read_text())


if __name__ == "__main__":
    unittest.main()
