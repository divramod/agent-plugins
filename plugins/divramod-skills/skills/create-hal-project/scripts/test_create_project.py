#!/usr/bin/env python3
"""Tests for create_project.py: a temp HOME, a fake gh on PATH backed by local bare repos, real git (offline)."""
import contextlib
import io
import json
import os
import shutil
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
import foundation  # noqa: E402

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


class CreateProjectBase(unittest.TestCase):
    """A temp HOME with a fake gh. The sandbox sits at one path per class: the state after a full run (clone,
    commit, push, hook) is made once, frozen, and copied back to that path for each test that starts from it
    (docs/fast-tests.md: a fixture is built once, the copy lands at the template's own path, its absolute links stay)."""
    clean_git = False

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="hal-create-project-"))
        cls.addClassCleanup(shutil.rmtree, cls.root, True)
        cls.sandbox, cls.frozen = cls.root / "sandbox", cls.root / "created"
        cls.is_frozen = False

    def setUp(self):
        t = self.sandbox
        shutil.rmtree(t, ignore_errors=True)
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
        if self.clean_git:
            self.env["GIT_CONFIG_GLOBAL"] = "/dev/null"

    def created(self) -> None:
        """The sandbox after one full run, as the first test that asks makes it and every later one gets it back."""
        cls = type(self)
        if not cls.is_frozen:
            self.cli()
            shutil.copytree(self.sandbox, cls.frozen, symlinks=True)
            cls.is_frozen = True
            return
        shutil.rmtree(self.sandbox)
        shutil.copytree(cls.frozen, self.sandbox, symlinks=True)

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


class GitTests:
    """The tests whose outcome depends on git's defaults (clone, default branch, commit, push, hooks path): run with
    this machine's git config and again with none (CleanGit)."""

    def test_full_run_creates_and_rerun_is_all_exists(self):
        self.created()
        folder = self.home / "a" / "voice-agent"
        bare = self.gh / "divramod" / "voice-agent.git"
        self.assertIn(["repo", "create", "divramod/voice-agent", "--private"], self.gh_calls())
        self.assertEqual(self.git("log", "--format=%s", "main", cwd=bare), "chore: init voice-agent as a hal project")
        tracked = self.git("ls-files", cwd=folder).splitlines()
        for path in ("README.md", "CLAUDE.md", "AGENTS.md", "INTENT.md", "GLOSSARY.md", ".gitignore",
                     "roles/farmer/ROLE.md", "roles/farmer/.gitignore", "plans/.gitkeep", ".adr/.gitkeep",
                     "docs/.gitkeep", "research/.gitkeep", "designs/.gitkeep", "code/.gitkeep",
                     "assets/logos/.gitkeep", "shotfiles/.gitkeep", "LICENSE", ".gitattributes", ".hal/setup.toml",
                     ".hal/cleanup", "code/bash/scripts/gate/main.sh", "code/bash/scripts/gate/lib.sh",
                     "code/bash/scripts/pre-push/main.sh"):
            self.assertIn(path, tracked)
        self.assertEqual(sorted(tracked), sorted(set(tracked)))
        modes = {line.split("\t")[1]: line.split()[0] for line in self.git("ls-files", "-s", cwd=folder).splitlines()}
        for path in foundation.EXECUTABLE:
            self.assertEqual(modes[path], "100755", path)
        self.assertEqual(modes["code/bash/scripts/gate/lib.sh"], "100644")
        hook = folder / ".git" / "hooks" / "pre-push"
        self.assertIn(foundation.HOOK_MARK, hook.read_text())
        self.assertTrue(os.access(hook, os.X_OK))
        for path in tracked:
            self.assertNotIn("{name}", (folder / path).read_text(errors="replace"), path)
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

    def test_existing_repo_with_commits_is_cloned_never_changed(self):
        bare = self.gh / "divramod" / "voice-agent.git"
        seed = self.sandbox / "seed"
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
        self.assertEqual(actions["file", "code/bash/scripts/gate/main.sh"]["state"], "skip")
        self.assertEqual(actions["hook", "pre-push"]["state"], "skip")
        self.assertEqual(actions["commit", "chore: init voice-agent as a hal project"]["state"], "exists")
        folder = self.home / "a" / "voice-agent"
        self.assertEqual((folder / "README.md").read_text(), "theirs\n")
        self.assertFalse((folder / "INTENT.md").exists())
        self.assertFalse((folder / ".git" / "hooks" / "pre-push").exists())
        self.assertEqual(self.git("log", "--format=%s", "main", cwd=bare), "theirs")

    def test_missing_hook_is_linked_on_a_rerun(self):
        self.created()
        hook = self.home / "a" / "voice-agent" / ".git" / "hooks" / "pre-push"
        hook.unlink()
        actions = self.plan()
        self.assertEqual(actions["hook", "pre-push"]["state"], "create")
        self.assertEqual({a["state"] for k, a in actions.items() if k[0] == "file"}, {"exists"})
        self.cli()
        self.assertIn(foundation.HOOK_MARK, hook.read_text())

    def test_foreign_hook_is_reported_and_kept(self):
        self.created()
        hook = self.home / "a" / "voice-agent" / ".git" / "hooks" / "pre-push"
        hook.write_text("#!/bin/sh\necho mine\n")
        action = self.plan()["hook", "pre-push"]
        self.assertEqual((action["state"], action["detail"]), ("skip", "another tool's hook, left alone"))
        self.cli()
        self.assertEqual(hook.read_text(), "#!/bin/sh\necho mine\n")


class PlainTests:
    """The rest: plans, files, smug ymls and the gate do not use git's defaults, so they run once."""

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
        for path in ("code/bash/scripts/gate/main.sh", ".hal/setup.toml", "LICENSE", "shotfiles/.gitkeep"):
            self.assertEqual(actions["file", path]["state"], "create", path)
        self.assertEqual(actions["hook", "pre-push"]["state"], "create")
        self.assertFalse((self.home / "a").exists())

    def test_foreign_folder_stops(self):
        folder = self.home / "a" / "voice-agent"
        folder.mkdir(parents=True)
        (folder / "notes.txt").write_text("mine")
        r = self.cli(code=3)
        self.assertIn("not a checkout", r.stderr)
        self.assertEqual(list(self.gh.rglob("*.git")), [])
        self.assertEqual((self.smug / "hal9k-1.yml").read_text(), HAL9K)

    def test_foundation_gate_is_green_in_the_created_repo(self):
        # the jobs of the created repo; the bash-test job (bats) runs once, in test_templates' one `gate all`
        self.created()
        folder = self.home / "a" / "voice-agent"
        for job in ("bash-lint", "python-test", "secrets-scan"):
            r = subprocess.run(["bash", "code/bash/scripts/gate/main.sh", job], cwd=folder, env=self.env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{job}\n{r.stdout}{r.stderr}")
        self.assertEqual(self.git("status", "--porcelain", cwd=folder), "", "the gate left files behind")

    def test_next_steps_name_the_gate_and_the_license(self):
        steps = " ".join(json.loads(self.cli("--dry-run", "--json").stdout)["next"])
        self.assertIn("code/bash/scripts/gate/main.sh all", steps)
        self.assertIn("LICENSE", steps)

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


class TestCreateProject(GitTests, PlainTests, CreateProjectBase):
    pass


class TestCreateProjectCleanGit(GitTests, CreateProjectBase):
    """The git-dependent tests again with no global git config, as on CI (plan 0403's train went red on a
    default-branch difference)."""
    clean_git = True


if __name__ == "__main__":
    unittest.main()
