#!/usr/bin/env python3
"""Tests of the new repo's templates (plan 0408): rendered into a temp git repo and committed, the generated gate
must be green (`gate/main.sh all`), the pre-push hook must install and gate a real push, the ignore rules must keep
secrets out; with this machine's git and with a clean one (no system or global config, a temp HOME)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import create_project  # noqa: E402
import foundation  # noqa: E402

GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
BAD_SHELL = '#!/usr/bin/env bash\nset -eu\nx="a b"\nls $x\n'  # SC2086: an unquoted variable


def render_repo(root: Path, name: str = "voice-agent", alias: str = "va") -> None:
    """Write the first commit's files as create_project.py will: its flat LAYOUT plus the foundation."""
    for path in create_project.first_commit_paths():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(create_project.render(path, name, alias))
        target.chmod(0o755 if path in foundation.EXECUTABLE else 0o644)


class TemplatesBase(unittest.TestCase):
    """The rendered, committed template repo is built once per class (setUpClass); a test that only reads it uses it,
    one that changes it gets a copy (docs/fast-tests.md: a fixture is built once). The real gate runs once per class."""
    clean_git = False
    run_gate = False

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="hal-templates-"))
        cls.addClassCleanup(shutil.rmtree, cls.root, True)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "GATE_", "PRE_PUSH"))}
        env.pop("CI", None)  # a missing tool skips locally; on CI=true it would fail the job
        if cls.clean_git:
            (cls.root / "home").mkdir()
            env.update(HOME=str(cls.root / "home"), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")
        cls.env = env
        cls.template = cls.root / "template"
        cls.template.mkdir()
        render_repo(cls.template)
        cls.run_at(cls.template, "git", "init", "-q", "-b", "main")
        cls.run_at(cls.template, "git", "add", "-A")
        cls.run_at(cls.template, "git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                   "commit", "-q", "-m", "chore: init voice-agent as a hal project")
        cls.gate_future = None
        if cls.run_gate:  # in the background while the other tests run; the tests that need it wait for it
            cls.addClassCleanup(cls.shutdown_gate)
            cls.pool = ThreadPoolExecutor(1)
            cls.gate_future = cls.pool.submit(cls.run_gate_all)

    @classmethod
    def shutdown_gate(cls):
        cls.pool.shutdown(wait=True)

    @classmethod
    def run_at(cls, cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        r = subprocess.run(list(args), cwd=cwd, env=cls.env, capture_output=True, text=True, timeout=600)
        if check and r.returncode != 0:
            raise AssertionError(f"{' '.join(args)} exited {r.returncode}:\n{r.stdout}\n{r.stderr}")
        return r

    def setUp(self):
        self.repo = self.template  # read-only tests; a test that changes the repo calls own_copy()
        self.tmp = Path(tempfile.mkdtemp(prefix="hal-templates-test-", dir=self.root))

    def own_copy(self) -> None:
        """A private copy of the template repo (no absolute links in it: no remote, no worktree)."""
        self.repo = self.tmp / "repo"
        shutil.copytree(self.template, self.repo, symlinks=True)

    def run_in(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return self.run_at(self.repo, *args, check=check)

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return self.run_in("git", *args, check=check)

    def gate(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return self.run_in("bash", "code/bash/scripts/gate/main.sh", *args, check=check)

    @classmethod
    def run_gate_all(cls) -> tuple[subprocess.CompletedProcess, str]:
        """`gate all` in a copy of the template, once: its result and the copy's `git status --porcelain` after it."""
        repo = cls.root / "gate-all"
        shutil.copytree(cls.template, repo, symlinks=True)
        r = cls.run_at(repo, "bash", "code/bash/scripts/gate/main.sh", "all", check=False)
        return r, cls.run_at(repo, "git", "status", "--porcelain").stdout

    @classmethod
    def gate_all(cls) -> tuple[subprocess.CompletedProcess, str]:
        return cls.gate_future.result()


class GitTests:
    """The tests whose outcome depends on git's defaults (branch, ignore, modes, hooks, push): run with this
    machine's git config and again with none (TemplatesCleanGit)."""

    def test_pre_push_installs_and_gates_a_real_push(self):
        self.own_copy()
        r = self.run_in(*foundation.INSTALL)
        self.assertIn("wrote ", r.stdout)
        hook = self.repo / ".git/hooks/pre-push"
        self.assertTrue(os.access(hook, os.X_OK))
        self.assertIn("is current", self.run_in(*foundation.INSTALL).stdout)
        remote = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], env=self.env, check=True)
        self.git("remote", "add", "origin", str(remote))
        first = self.git("push", "-q", "-u", "origin", "main")
        self.assertIn("pre-push:", first.stdout + first.stderr)
        self.git("checkout", "-q", "-b", "topic")
        script = self.repo / "code/bash/scripts/bad/main.sh"
        script.parent.mkdir(parents=True)
        script.write_text(BAD_SHELL)
        self.git("add", "-A")
        self.git(*GIT_ID, "commit", "-q", "-m", "feat: a bad script")
        pushed = self.git("push", "-q", "origin", "topic", check=False)
        if shutil.which("shellcheck", path=self.env.get("PATH")):
            self.assertNotEqual(pushed.returncode, 0, pushed.stdout + pushed.stderr)
            self.assertIn("bash-lint FAILED", pushed.stderr)
        else:
            self.assertEqual(pushed.returncode, 0, pushed.stderr)  # the job skipped: no shellcheck here
            self.assertIn("bash-lint ok", pushed.stdout + pushed.stderr)

    def test_install_leaves_a_foreign_hook_alone(self):
        self.own_copy()
        hook = self.repo / ".git/hooks/pre-push"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\necho foreign\n")
        r = self.run_in(*foundation.INSTALL, check=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("another tool's hook", r.stderr)
        self.assertEqual(hook.read_text(), "#!/bin/sh\necho foreign\n")

    def test_secrets_and_env_files_stay_out_of_git(self):
        ignored = [".secrets/API_TOKEN_SEC", ".secrets/05/API_TOKEN_SEC", ".env", ".env.local", "shotfiles/a.md",
                   "plans/CURRENT_PLAN", ".gitsecret/keys/random_seed"]
        kept = [".secrets/API_TOKEN_SEC.secret", ".env.example", ".env.local.example", "shotfiles/.gitkeep"]
        # one git call for all paths: `check-ignore --stdin` prints exactly the ignored ones
        r = subprocess.run(["git", "check-ignore", "--stdin"], cwd=self.repo, env=self.env, input="\n".join(ignored + kept),
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.split(), ignored, r.stdout + r.stderr)
        tracked = self.git("ls-files").stdout.split()
        for path in ("shotfiles/.gitkeep", "LICENSE", ".gitattributes", ".hal/setup.toml", ".hal/cleanup"):
            self.assertIn(path, tracked)
        self.assertEqual(self.git("check-attr", "binary", "--", ".secrets/A_SEC.secret").stdout.split()[-1], "set")

    def test_layout_names_and_modes(self):
        for folder in foundation.KEEP_DIRS:
            self.assertTrue((self.repo / folder / ".gitkeep").is_file(), folder)
        modes = dict(line.split()[3:4] + line.split()[:1] for line in self.git("ls-files", "-s").stdout.splitlines())
        for path in foundation.EXECUTABLE:
            self.assertEqual(modes[path], "100755", path)
        self.assertEqual(modes["code/bash/scripts/gate/lib.sh"], "100644")
        readme = (self.repo / "README.md").read_text()
        self.assertIn("## Making it public", readme)
        self.assertIn("voice-agent", (self.repo / "LICENSE").read_text())


class Templates(GitTests, TemplatesBase):
    """The git-independent tests (the gate, its bats, a python unit) run once, with this machine's git config."""
    run_gate = True

    def test_gate_all_is_green_on_the_fresh_layout(self):
        r, status = self.gate_all()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for job in ("bash-lint", "bash-test", "python-test", "secrets-scan"):
            self.assertRegex(r.stdout, rf"ok +{job} ")
        self.assertEqual(status, "", "the gate left files behind")

    def test_the_bats_suites_of_gate_and_pre_push_pass(self):
        if not shutil.which("bats", path=self.env.get("PATH")):
            self.skipTest("bats is not installed: bash-test skips (brew install bats-core)")
        r, _ = self.gate_all()  # bash-test's bats output is part of the one gate run
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok 1 ", r.stdout)
        self.assertNotIn("not ok", r.stdout)

    def test_a_python_unit_runs_in_python_test(self):
        self.own_copy()
        unit = self.repo / "code/python/scripts/hello"
        unit.mkdir(parents=True)
        (unit / "test_main.py").write_text("import unittest\n\n\nclass T(unittest.TestCase):\n"
                                           "    def test_ok(self):\n        self.assertTrue(True)\n")
        r = self.gate("python-test")
        self.assertIn("python-test: code/python/scripts/hello", r.stdout)
        (unit / "test_main.py").write_text((unit / "test_main.py").read_text().replace("True)", "False)"))
        self.assertNotEqual(self.gate("python-test", check=False).returncode, 0)

    def test_list_names_every_job(self):
        out = self.gate("list").stdout
        for job in ("bash-lint", "bash-test", "python-test", "secrets-scan"):
            self.assertIn(job, out)


class TemplatesCleanGit(GitTests, TemplatesBase):
    """Only the git-dependent tests again, with no system or global git config and a temp HOME, as on CI (plan 0403's
    red train); the rest does not use git's defaults (plan 0408 step 5)."""
    clean_git = True


class TemplateFiles(unittest.TestCase):
    def test_no_placeholder_left_and_every_file_small(self):
        for path, (text, _) in foundation.files("voice-agent", "va").items():
            self.assertNotIn("{name}", text, path)
            self.assertNotIn("{alias}", text, path)
            code = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
            self.assertLessEqual(len(code), 300, path)

    def test_scripts_run_on_bash_3_2(self):
        check = HERE.parents[6] / "bash/scripts/bash32-check/main.sh"  # hal2's static check, absent once published
        if not check.is_file():
            self.skipTest(f"{check} is not here (a published copy of the skill)")
        with tempfile.TemporaryDirectory() as tmp:
            render_repo(Path(tmp))
            scripts = sorted(str(p) for p in Path(tmp).rglob("*.sh"))
            r = subprocess.run(["bash", str(check), *scripts], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_paths_and_install(self):
        paths = foundation.paths()
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(set(foundation.EXECUTABLE) <= set(paths))
        self.assertFalse(set(paths) & set(create_project.LAYOUT) - {f"{d}/.gitkeep" for d in foundation.KEEP_DIRS})
        self.assertEqual(foundation.INSTALL[1], "code/bash/scripts/pre-push/main.sh")


if __name__ == "__main__":
    unittest.main()
