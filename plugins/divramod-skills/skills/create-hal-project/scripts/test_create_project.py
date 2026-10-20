#!/usr/bin/env python3
"""Tests for create_project.py: a temp HOME, a fake gh on PATH backed by local bare repos, real git (offline)."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "create_project.py"
sys.path.insert(0, str(HERE))
import create_project  # noqa: E402

FAKE_GH = r'''#!PYTHON
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
bare = os.path.join(os.environ["FAKE_GH"], args[2] + ".git")
if args[:2] == ["repo", "view"]:
    if not os.path.isdir(bare):
        sys.exit(print("GraphQL: Could not resolve to a Repository with the name '" + args[2] + "'.",
                       file=sys.stderr) or 1)
    refs = subprocess.run(["git", "-C", bare, "for-each-ref"], capture_output=True, text=True).stdout
    print(json.dumps({"sshUrl": bare, "isEmpty": not refs.strip()}))
elif args[:2] == ["repo", "create"] and "--private" in args:
    subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main", bare], check=True)
    print("https://github.com/" + args[2])
else:
    sys.exit(print("fake gh: unexpected " + " ".join(args), file=sys.stderr) or 1)
'''

HAL9K = """session: hal9k-1
root: ~/a
windows:

  - name: tmux
    root: ~/a
    commands:
      - # claude
    panes:
      - commands:
        - vim ~/.config/smug/hal9k-1.yml

  - name: i
    focus: true
    root: ~/a/i
    commands:
      - hal2-cli-git worktree run main --agent claude

  - name: vi
    focus: true
    root: ~/a/village
    layout: even-horizontal
    commands:
      - # claude --remote-control "village" --continue
    panes:
      - commands:
        - hal2-cli-git worktree run farmer-village --agent claude
        - cd ~/.hal/git/worktree/village

#    layout: 289c,212x62
"""

SHO = """session: sho
root: ~/sho
windows:
    - name: tmux
      root: ~/a/shooter
    - name: api
      root: ~/a/shooter
"""

EXISTING = """session: b
windows:
  - name: va
    root: ~/elsewhere
"""


class TestCreateProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.home, self.gh, self.bin = t / "home", t / "gh", t / "bin"
        for d in (self.home, self.gh / "divramod", self.bin):
            d.mkdir(parents=True)
        (self.bin / "gh").write_text(FAKE_GH.replace("PYTHON", sys.executable, 1))
        (self.bin / "gh").chmod(0o755)
        self.smug = self.home / ".config" / "smug"
        self.smug.mkdir(parents=True)
        (self.smug / "hal9k-1.yml").write_text(HAL9K)
        (self.smug / "sho.yml").write_text(SHO)
        (self.smug / "b.yml").write_text(EXISTING)
        self.log = t / "gh.log"
        who = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(self.home),
                    "FAKE_GH": str(self.gh), "FAKE_LOG": str(self.log), "GIT_CONFIG_NOSYSTEM": "1",
                    "LANG": "C", **who}

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args: str, code: int = 0) -> subprocess.CompletedProcess:
        """create_project.main in-process, with the temp HOME and PATH (the real-process run: test_bad_name)."""
        out, err, exit_code = io.StringIO(), io.StringIO(), 0
        argv = ["create_project.py", "voice-agent", "va", *args]
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                create_project.main()
            except SystemExit as e:
                exit_code = e.code if isinstance(e.code, int) else 1
        r = subprocess.CompletedProcess(argv, exit_code, out.getvalue(), err.getvalue())
        self.assertEqual(r.returncode, code, r.stderr + r.stdout)
        return r

    def plan(self, *args: str) -> dict:
        actions = json.loads(self.cli("--json", *args).stdout)["actions"]
        return {(a["kind"], a["target"]): a for a in actions}

    def snapshot(self) -> dict:
        return {str(p): p.read_bytes() if p.is_file() else None
                for root in (self.home, self.gh) for p in sorted(root.rglob("*"))}

    def gh_calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def git(self, *args: str, cwd: Path) -> str:
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True,
                              check=True).stdout.strip()

    def test_dry_run_changes_nothing(self):
        before = self.snapshot()
        out = self.cli("--dry-run").stdout
        self.assertEqual(before, self.snapshot())
        self.assertIn("dry run", out)
        self.assertIn("Next steps", out)
        actions = self.plan("--dry-run")
        self.assertEqual(actions["repo", "divramod/voice-agent"]["state"], "create")
        self.assertEqual(actions["file", "roles/farmer/ROLE.md"]["state"], "create")
        self.assertEqual(actions["smug", str(self.smug / "hal9k-1.yml")]["state"], "create")
        self.assertEqual(actions["smug", str(self.smug / "b.yml")]["state"], "exists")
        self.assertEqual(actions["smug", str(self.smug / "a.yml")]["state"], "skip")
        self.assertNotIn("create", [c[1] for c in self.gh_calls()])

    def test_full_run_creates_and_rerun_is_all_exists(self):
        self.cli()
        folder = self.home / "a" / "voice-agent"
        bare = self.gh / "divramod" / "voice-agent.git"
        self.assertIn(["repo", "create", "divramod/voice-agent", "--private"], self.gh_calls())
        self.assertEqual(self.git("log", "--format=%s", "main", cwd=bare), "chore: init voice-agent as a hal project")
        tracked = self.git("ls-files", cwd=folder).splitlines()
        for path in ("README.md", "CLAUDE.md", "AGENTS.md", "INTENT.md", "GLOSSARY.md", ".gitignore",
                     "roles/farmer/ROLE.md", "roles/farmer/.gitignore", "plans/.gitkeep", ".adr/.gitkeep",
                     "docs/.gitkeep", "research/.gitkeep", "designs/.gitkeep"):
            self.assertIn(path, tracked)
        self.assertIn("farmer-voice-agent", (folder / "README.md").read_text())
        self.assertNotIn("{name}", (folder / "AGENTS.md").read_text())
        role = (folder / "roles/farmer/ROLE.md").read_text()
        self.assertTrue(role.startswith("---\n"))
        self.assertIn("# voice-agent's farmer role", role)
        self.assertIn("plans/CURRENT_PLAN", (folder / ".gitignore").read_text())
        hal9k = (self.smug / "hal9k-1.yml").read_text()
        self.assertTrue(hal9k.endswith("\n  - name: va\n    root: ~/a/voice-agent\n    layout: even-horizontal\n"
                                       "    commands:\n      - # claude --remote-control \"voice-agent\" --continue\n"
                                       "    panes:\n      - commands:\n"
                                       "        - hal2-cli-git worktree run farmer-voice-agent --agent claude\n"
                                       "        - cd ~/.hal/git/worktree/voice-agent\n"), hal9k)
        self.assertEqual(hal9k.count("focus: true"), 2)
        self.assertIn("    - name: va\n      root: ~/a/voice-agent\n", (self.smug / "sho.yml").read_text())
        self.assertEqual((self.smug / "b.yml").read_text(), EXISTING)
        self.assertEqual(self.git("status", "--porcelain", cwd=folder), "")

        before, calls = self.snapshot(), len(self.gh_calls())
        states = {a["state"] for a in self.plan().values() if a["detail"] != "no such file"}
        self.assertEqual(states, {"exists"})
        self.assertEqual(before, self.snapshot())
        self.assertNotIn("create", [c[1] for c in self.gh_calls()[calls:]])

    def test_foreign_folder_stops(self):
        folder = self.home / "a" / "voice-agent"
        folder.mkdir(parents=True)
        (folder / "notes.txt").write_text("mine")
        r = self.cli(code=3)
        self.assertIn("not a checkout", r.stderr)
        self.assertEqual(list(self.gh.rglob("*.git")), [])
        self.assertEqual((self.smug / "hal9k-1.yml").read_text(), HAL9K)

    def test_existing_repo_with_commits_is_cloned_never_changed(self):
        bare = self.gh / "divramod" / "voice-agent.git"
        seed = Path(self.tmp.name) / "seed"
        subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main", str(bare)], check=True)
        subprocess.run(["git", "clone", "-q", str(bare), str(seed)], env=self.env, check=True, capture_output=True)
        (seed / "README.md").write_text("theirs\n")
        self.git("add", "README.md", cwd=seed)
        self.git("commit", "-q", "-m", "theirs", cwd=seed)
        self.git("push", "-q", "origin", "HEAD:main", cwd=seed)
        actions = self.plan()
        self.assertEqual(actions["repo", "divramod/voice-agent"]["state"], "exists")
        self.assertEqual(actions["checkout", str(self.home / "a" / "voice-agent")]["state"], "create")
        self.assertEqual(actions["file", "INTENT.md"]["state"], "skip")
        self.assertEqual(actions["commit", "chore: init voice-agent as a hal project"]["state"], "exists")
        folder = self.home / "a" / "voice-agent"
        self.assertEqual((folder / "README.md").read_text(), "theirs\n")
        self.assertFalse((folder / "INTENT.md").exists())
        self.assertEqual(self.git("log", "--format=%s", "main", cwd=bare), "theirs")

    def test_window_by_root_is_kept(self):
        text = HAL9K.replace("name: vi\n", "name: vill\n").replace("~/a/village", "~/a/voice-agent")
        (self.smug / "hal9k-1.yml").write_text(text)
        actions = self.plan("--smug", "hal9k-1.yml")
        self.assertEqual(actions["smug", str(self.smug / "hal9k-1.yml")]["detail"], "window vill")
        self.assertEqual((self.smug / "hal9k-1.yml").read_text(), text)

    def test_bad_name_is_refused_as_a_real_process(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "../x", "va", "--dry-run"], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("name: letters", r.stderr)


if __name__ == "__main__":
    unittest.main()
