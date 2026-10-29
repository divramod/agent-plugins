"""A scratch farm whose plans live in its plan store, for the skills' store-home tests (hal2 plan 0409 steps 8-9).

    from store_testkit import DEBUG, StoreFarm   # (the plan skill's scripts/ on sys.path)

    @unittest.skipUnless(DEBUG, "no hal2-cli-plans with the store home")
    class X(StoreFarm, unittest.TestCase):
        def test_it(self):
            self.cli("new", "A plan", "--no-current")   # the store numbers it: 0001-a-plan

`StoreFarm.setUp` makes `self.repo` (git, `home store`, no `.gitignore`: the pointers live in the git dir) with the
environment pointed into a temp folder (data, state, config, HOME), `HAL2_CLI_PLANS` naming the binary; `DEBUG` is
this checkout's debug build of hal2-cli-plans, else the installed one when it has the store home's commands, else None.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent


def store_cli() -> Path | None:
    for parent in HERE.parents:
        debug = parent / "code/rust/target/debug" / ("hal2-cli-plans.exe" if os.name == "nt" else "hal2-cli-plans")
        if debug.is_file():
            return debug
    found = shutil.which("hal2-cli-plans")
    if not found:
        return None
    done = subprocess.run([found, "help", "sync"], capture_output=True, text=True)
    return Path(found) if "--if-due" in done.stdout else None


DEBUG = store_cli()


class StoreFarm:
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="store-farm-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        env = {"HAL2_CLI_PLANS": str(DEBUG), "HAL2_DATA_ROOT": str(self.tmp / "data"),
               "HAL2_STATE_DIR": str(self.tmp / "state"), "HAL2_CONFIG_DIR": str(self.tmp / "config"),
               "HOME": str(self.tmp / "home"), "HAL2_HOME": str(self.tmp / "home"),
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t", "CLAUDE_CODE_SESSION_ID": ""}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        self.git("init", "-q", "-b", "main")
        self.git("commit", "-q", "--allow-empty", "-m", "init")  # no .gitignore: hal's files stay out of the tree
        self.assertEqual(self.cli("home", "store")["home"], "store")
        for name in ("planhome", "planread"):  # a process-wide cache of an earlier test's farm
            module = sys.modules.get(name)
            for cache in ("_HOMES", "_KIND", "_DIRS"):
                getattr(module, cache, {}).clear()

    def git(self, *args: str) -> str:
        done = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def run_ok(self, *cmd: str) -> str:
        done = subprocess.run([*cmd], cwd=self.repo, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, f"{cmd}: {done.stdout}{done.stderr}")
        return done.stdout

    def cli(self, *args: str) -> dict:
        return json.loads(self.run_ok(str(DEBUG), *args, "--json"))

    def rendered(self, plan: str) -> list[str]:
        """The files the store holds for `plan`, as `render` writes them."""
        return self.cli("render", plan, "--to", str(self.tmp / "check"))["files"]

    def assert_clean(self):
        """`git status` empty with no `.gitignore` at all, no `plans/` folder (hal2 plan 0409 step 12)."""
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all"), "")
        self.assertFalse((self.repo / ".gitignore").exists(), "no hal line in a .gitignore")
        self.assertFalse((self.repo / "plans").exists(), "no plans/ folder, not even a pointer")
