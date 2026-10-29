#!/usr/bin/env python3
"""Tests for implement.py with fake hal2 CLIs on PATH (offline: no agent is started, nothing is typed)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
COORDINATOR = ("You are the plan's coordinator: you never do a step yourself; each step runs in one subagent at its "
               "row's Model and Effort, sized under 35% of its Window; you check its done-when, commit it and keep "
               "`run` current.")

# hal2: create.py's free-disk check reads shutil.disk_usage; a sitecustomize on PYTHONPATH makes the subprocesses see
# FAKE_FREE_GB (default 1000) free, so the tests pass on a machine or CI runner with less than 50 GB free.
DISK = """import collections, os, shutil
_usage = collections.namedtuple("usage", "total used free")
_free = int(float(os.environ.get("FAKE_FREE_GB", "1000")) * 2**30)
shutil.disk_usage = lambda path: _usage(_free, 0, _free)
"""

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
log = os.environ["FAKE_LOG"]
with open(log, "a") as f:
    f.write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:]) + "\n")
args = sys.argv[1:]
repo = os.environ["FAKE_REPO"]
if args[:2] == ["shots", "list-open"]:
    print(json.dumps({"shots": [{"number": "4", "title": "tabs: sort button", "body": "A button that sorts tabs.",
                                 "path": repo + "/shotfiles/app.md"}]}))
elif args[:2] == ["shots", "mark-sent"]:
    print("{}")
elif args[:1] == ["list"]:
    print(json.dumps([{"pane_id": "%7", "slot": "03", "kind": "claude", "state": "working", "title": "t",
                       "project": repo, "session_id": "s7"}, {"pane_id": "%9", "slot": "01", "kind": "claude",
                       "state": "idle", "project": "/elsewhere"}]))
elif args[:2] == ["terminal", "list"]:
    print("[]")
elif args[:2] == ["worktree", "list"]:
    print(json.dumps({"worktrees": [{"name": "main", "main": True}, {"name": "01", "plan": "0001-busy"}]}))
elif args[:2] == ["worktree", "queue"]:
    print(json.dumps({"queue": []}))
elif args[:2] == ["worktree", "run"]:
    print(json.dumps({"mode": "terminal", "pane": "t:abc", "slot": args[2], "worktree": "/wt/" + args[2]}))
'''


class TestImplement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.repo = t / "app"
        (self.repo / "shotfiles").mkdir(parents=True)
        (self.repo / "shotfiles" / "app.md").write_text("# app\n\n## shot 4 tabs: sort button\nA button that sorts tabs.\n")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "remote", "add", "origin", "git@github.com:me/app.git"], check=True)
        self.bin = t / "bin"
        self.bin.mkdir()
        for name in ("hal2-cli-shooter", "hal2-cli-agents", "hal2-cli-git"):
            (self.bin / name).write_text(FAKE)
            (self.bin / name).chmod(0o755)
        (self.bin / "fakeshell").write_text('#!/bin/sh\nexec /bin/sh -c "$2"\n')
        (self.bin / "fakeshell").chmod(0o755)
        (self.bin / "sitecustomize.py").write_text(DISK)
        self.log = t / "log"
        self.home = t / "home"
        self.home.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_imp(self, *args, ok=True):
        env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}", HOME=str(self.home), SHELL=str(self.bin / "fakeshell"),
                   FAKE_LOG=str(self.log), FAKE_REPO=str(self.repo.resolve()), PYTHONPATH=str(self.bin))
        r = subprocess.run([sys.executable, str(HERE / "implement.py"), *args], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode == 0, ok, r.stderr)
        return json.loads(r.stdout) if ok else r.stderr

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def transcript(self, model="claude-opus-5-5", effort="medium"):
        """Session s7's transcript: one main-chain turn at `model` and `effort`."""
        folder = self.home / ".claude" / "projects" / "-app"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "s7.jsonl").write_text(json.dumps({"type": "assistant", "requestedModel": model, "effort": effort,
                                                     "message": {"content": []}}) + "\n")

    def test_new_worktree_gets_the_shot_prompt_then_the_shot_is_marked(self):
        out = self.run_imp("send", "--repo", str(self.repo), "--shotfile", "app", "--number", "4")
        self.assertEqual((out["mode"], out["slot"], out["remote_control"]), ("new", "02", "app-02"))
        spawn = next(c for c in self.calls() if c[1:3] == ["worktree", "run"])
        prompt = spawn[spawn.index("--prompt") + 1]
        self.assertIn("# shot 4 tabs: sort button (app)\nA button that sorts tabs.", prompt)
        self.assertIn('This is shot 4 of the feature "app" in repo me/app.', prompt)
        self.assertIn("titled `app 4 tabs: sort button`", prompt)
        self.assertIn("then run it as its coordinator. " + COORDINATOR, prompt)
        self.assertEqual(prompt.count(COORDINATOR), 1)
        self.assertEqual(spawn[spawn.index("--model") + 1:spawn.index("--model") + 4], ["opus", "--effort", "medium"])
        self.assertEqual(Path(out["bullet"]).read_text().strip(), prompt)
        mark = self.calls()[-1]
        self.assertEqual(mark[1:4] + mark[mark.index("--worktree"):mark.index("--worktree") + 2],
                         ["shots", "mark-sent", "app", "--worktree", "02"])

    def test_new_session_takes_the_given_model_and_effort(self):
        self.run_imp("send", "--repo", str(self.repo), "--shotfile", "app", "--number", "4", "--model", "sonnet",
                     "--effort", "high")
        spawn = next(c for c in self.calls() if c[1:3] == ["worktree", "run"])
        self.assertEqual(spawn[spawn.index("--model") + 1:spawn.index("--model") + 4], ["sonnet", "--effort", "high"])
        self.assertIn("--effort is one of", self.run_imp("send", "--repo", str(self.repo), "--shotfile", "app",
                                                         "--number", "4", "--effort", "huge", ok=False))

    def test_a_template_without_the_sentence_gets_it(self):
        folder = self.repo / ".hal/util/shooter/config/nvim"
        folder.mkdir(parents=True)
        (folder / "shot-template-single.md").write_text("# shot {{shot_title}}\n{{shot_content}}\n")
        self.run_imp("send", "--repo", str(self.repo), "--shotfile", "app", "--number", "4")
        spawn = next(c for c in self.calls() if c[1:3] == ["worktree", "run"])
        self.assertTrue(spawn[spawn.index("--prompt") + 1].endswith("\n\n" + COORDINATOR))

    def test_existing_session_at_other_values_is_switched_with_the_shot(self):
        self.transcript(effort="max")
        out = self.run_imp("send", "--repo", str(self.repo), "--shotfile", "app", "--number", "4", "--pane", "%7")
        self.assertEqual((out["mode"], out["switched"], out["was"]), ("existing", True,
                                                                      {"model": "claude-opus-5-5", "effort": "max"}))
        [switch] = [c[2:] for c in self.calls() if c[1] == "switch"]
        self.assertEqual(switch[:5], ["%7", "--model", "opus", "--effort", "medium"])
        self.assertIn(COORDINATOR, switch[switch.index("--prompt") + 1])
        self.assertFalse([c for c in self.calls() if c[1] == "send"])
        self.assertIn("03", self.calls()[-1])

    def test_existing_session_gets_the_bullet_typed_in(self):
        self.transcript()
        out = self.run_imp("send", "--repo", str(self.repo), "--shotfile", "app", "--number", "4", "--pane", "%7")
        self.assertEqual((out["mode"], out["slot"], out["busy"], out["switched"]), ("existing", "03", True, False))
        sends = [c[2:] for c in self.calls() if c[1] == "send"]
        self.assertEqual(sends, [["%7", "C-u", "--key"], ["%7", "@" + out["bullet"]], ["%7", "enter", "--key"],
                                 ["%7", "enter", "--key"]])
        self.assertIn("03", self.calls()[-1])

    def test_sessions_only_lists_this_repo_and_unknown_pane_fails(self):
        self.assertEqual([s["pane_id"] for s in self.run_imp("sessions", "--repo", str(self.repo))], ["%7"])
        err = self.run_imp("send", "--repo", str(self.repo), "--shotfile", "app", "--number", "4", "--pane", "%9",
                           ok=False)
        self.assertIn("no live agent session %9", err)
        self.assertFalse(any(c[1] in ("send", "mark-sent") or c[1:3] == ["shots", "mark-sent"] for c in self.calls()))

    def test_a_global_shot_is_read_and_marked_in_the_global_folder(self):
        out = self.run_imp("send", "--repo", str(self.repo), "--shotfile", "app", "--number", "4", "--global")
        self.assertEqual(out["slot"], "02")
        listed = next(c for c in self.calls() if c[1:3] == ["shots", "list-open"])
        self.assertIn("--global", listed)
        spawn = next(c for c in self.calls() if c[1:3] == ["worktree", "run"])
        prompt = spawn[spawn.index("--prompt") + 1]
        self.assertIn('the global shotfile "app", carried out in repo me/app', prompt)
        self.assertIn("titled `global app 4 tabs: sort button`", prompt)
        mark = self.calls()[-1]
        self.assertIn("--global", mark)
        self.assertEqual(mark[mark.index("--worktree") + 1], "app/02")


class TestStoreHome(unittest.TestCase):
    """A shotfile in the plan store has a virtual path (`store:farm/<name>.md`): its text comes from the CLI."""

    def test_the_text_of_a_store_shotfile_is_read_through_the_cli(self):
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location("implement", HERE / "implement.py")
        implement = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(implement)
        shown = json.dumps({"text": "# the feature\n\n## shot 4 tabs\n"})
        with mock.patch.object(implement, "run", return_value=shown) as run:
            text = implement.shotfile_text(Path("store:farm/app.md"), Path("/r"), "app", False)
        self.assertEqual(text, "# the feature\n\n## shot 4 tabs\n")
        self.assertEqual(run.call_args.args, ("hal2-cli-shooter", "shots", "show", "app", "--repo", "/r", "--json"))
        values = implement.prompt_values(Path("store:farm/app.md"), "4", "tabs", "body", "me/app", False, text)
        self.assertEqual(values["file_title"], "the feature")
        self.assertEqual(values["file_path"], "store:farm/app.md")


if __name__ == "__main__":
    unittest.main()
