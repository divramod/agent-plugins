"""The store home end to end (hal2 plan 0409 steps 8 and 12): a scratch farm whose plans live in its plan store runs a
plan with the skills' own scripts, `new` → `status <n> next` → the step's Task written in the edit copy → `prompt` →
`status done` → a commit → a handoff written → `/q`, then a root handoff and question with no plan, and nothing of
hal reaches the tree: `git status --porcelain` stays empty with no `.gitignore` at all and no `plans/` folder (the
pointers live in the git dir, the root HANDOFF.md and QUESTIONS.md in the store). Runs this checkout's debug build of hal2-cli-plans, else the installed one when it is new enough (skipped without); the files
home's behaviour is every other test's."""

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
# hal2's checkout: the first parent holding the Cargo workspace; in a copy of the suite (test_field_independent's
# shallow scratch tree, a published copy) none, and the root is this folder, so the checks below skip or use PATH.
ROOT = next((p for p in HERE.parents if (p / "code/rust/Cargo.toml").is_file()), HERE)


def store_cli() -> Path | None:
    """This checkout's debug build of hal2-cli-plans, else the one on PATH when it has the store home's commands (CI
    installs the candidate's); None when neither."""
    debug = ROOT / "code/rust/target/debug" / ("hal2-cli-plans.exe" if os.name == "nt" else "hal2-cli-plans")
    if debug.is_file():
        return debug
    found = shutil.which("hal2-cli-plans")
    if not found:
        return None
    done = subprocess.run([found, "help", "sync"], capture_output=True, text=True)
    return Path(found) if "--if-due" in done.stdout else None


DEBUG = store_cli()
PLAN = HERE / "plan.py"
HANDOFF = HERE.parents[1] / "handoff" / "scripts"
Q = HERE.parents[1] / "get-open-questions" / "scripts" / "q.py"
UAT = HERE.parents[1] / "user-acceptance-tests" / "scripts" / "uat.py"


@unittest.skipUnless(DEBUG, "no hal2-cli-plans with the store home (cargo build -p hal2-cli-plans)")
class StoreHome(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="plan-store-home-"))
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
        self.git("commit", "-q", "--allow-empty", "-m", "init")  # no .gitignore: nothing of hal lies in the tree
        self.assertEqual(self.cli("home", "store")["home"], "store")

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

    def plan(self, *args: str) -> dict:
        return json.loads(self.run_ok(sys.executable, str(PLAN), *args))

    def assert_clean(self):
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all"), "")
        for name in (".gitignore", "plans", "HANDOFF.md", "QUESTIONS.md"):
            self.assertFalse((self.repo / name).exists(), f"no {name} in the tree")

    def test_a_plan_runs_with_no_plan_file_in_the_tree(self):
        made = self.plan("new", "Store run", "--goal", "A plan with no files", "--no-current")
        self.assertEqual((made["slug"], made["path"]), ("0001-store-run", "plans/0001-store-run/plan.md"))
        self.assertFalse((self.repo / "plans").exists(), "no plans/ folder at all")
        self.assertEqual(self.cli("show", "1")["goal"], "A plan with no files")

        nexted = self.plan("status", "1", "next", "--plan", "1")
        self.assertEqual(nexted["step_file"], "plans/0001-store-run/steps/1.md")
        edit = self.plan("edit", "--plan", "1")
        self.assertEqual(edit["home"], "store")
        step = Path(edit["dir"]) / "steps" / "1.md"
        self.assertFalse(step.is_relative_to(self.repo), "the copy lies outside the tree")
        text = step.read_text()
        step.write_text(text.replace(text.split("## Task\n\n", 1)[1].split("\n", 1)[0], "Write the hello file."))
        self.assertEqual(self.plan("edit", "--plan", "1")["edited"], True)
        self.assertEqual(self.plan("apply")["applied"]["written"], 1)

        call = self.plan("prompt", "1", "--plan", "1")
        self.assertIn("your task plans/0001-store-run/steps/1.md", call["prompt"])
        self.assertIn("plan.py apply", call["prompt"], "the hand is told where the copy is")
        done = self.plan("status", "1", "done", "--plan", "1")
        self.assertEqual((done["done"], done["total"]), (1, 2))
        self.assertEqual(self.cli("show", "1")["steps"][0]["status"], "done")
        self.assertFalse((self.repo / "plans").exists())
        self.assert_clean()

        self.plan("use", "1")
        pointer = Path(self.git("rev-parse", "--absolute-git-dir").strip()) / "hal" / "CURRENT_PLAN"
        self.assertEqual(pointer.read_text(), "0001-store-run\n", "the pointer in the git dir")
        self.assertEqual(self.plan("current")["slug"], "0001-store-run")
        (self.repo / "hello.txt").write_text("hello\n")
        self.git("add", "hello.txt")
        trailers = self.run_ok(sys.executable, str(PLAN), "trailers", "1").strip()
        self.assertEqual(trailers, "", "neutral commits carry no origin trailers")
        self.git("commit", "-q", "-m", "feat: the hello file")
        self.assertEqual(self.cli("link-commit")["linked"], True, "the post-commit hook's link, into the store")
        self.assert_clean()
        where = json.loads(self.run_ok(sys.executable, str(HANDOFF / "where.py"), "--json", "--stamp"))
        self.assertEqual(where["form"], "record")
        handoff = Path(where["file"])
        self.assertFalse(handoff.is_relative_to(self.repo))
        handoff.write_text(handoff.read_text().rstrip("\n") + "\n\nstep 2, done when the UATs are written\n")
        out = self.run_ok("bash", str(HANDOFF / "commit-handoff.sh"), "docs(0001): the handoff", where["file"])
        self.assertIn("applied the plan's copy to the plan store", out)
        stored = self.tmp / "check"
        self.cli("render", "1", "--to", str(stored))
        self.assertIn("step 2, done when the UATs are written", (stored / "0001-store-run" / "handoff.md").read_text())
        self.assertEqual(self.git("log", "--oneline").count("\n"), 2, "the handoff is no commit")

        self.cli("questions", "add", "Which colour?", "--option", "red", "--option", "green", "--option", "blue")
        listed = self.run_ok(sys.executable, str(Q))
        self.assertIn("Which colour?", listed)
        self.assertIn("Which colour?", self.run_ok(sys.executable, str(Q), "--plan", "1"))
        questions = json.loads(self.run_ok(sys.executable, str(HANDOFF / "questions.py"), "--json"))
        self.assertEqual(len(questions["open"]), 1, questions)
        self.assertEqual(self.run_ok(sys.executable, str(UAT), "plan").strip(), "0001-store-run")
        self.assert_clean()

    def test_a_checkout_without_a_plan_keeps_its_root_files_in_the_store(self):
        where = json.loads(self.run_ok(sys.executable, str(HANDOFF / "where.py"), "--json"))
        self.assertEqual(where["form"], "legacy")
        handoff = Path(where["file"])
        self.assertEqual(handoff.name, "HANDOFF.md")
        self.assertFalse(handoff.is_relative_to(self.repo), "the root handoff's copy lies outside the tree")
        handoff.write_text("# Handoff\n\nnext: plan the hello file\n")
        out = self.run_ok("bash", str(HANDOFF / "commit-handoff.sh"), "docs: the handoff", str(handoff))
        self.assertIn("applied", out)
        again = json.loads(self.run_ok(sys.executable, str(HANDOFF / "where.py"), "--json"))
        self.assertEqual(Path(again["file"]).read_text(), "# Handoff\n\nnext: plan the hello file\n")
        self.cli("questions", "add", "Which size?", "--option", "s", "--option", "m", "--option", "l")
        self.assertIn("Which size?", self.run_ok(sys.executable, str(Q)))
        self.assertEqual(self.git("log", "--oneline").count("\n"), 1, "no commit")
        self.assert_clean()


@unittest.skipUnless((ROOT / "code/rust/libs/hal2-plans").is_dir(), "not in hal2's checkout (a published copy)")
class LedgerTemplates(unittest.TestCase):
    def test_the_stores_new_plan_writes_the_skills_ledgers(self):
        """hal2-plans makes a store plan's ledgers from copies of this skill's templates (it depends on no skill)."""
        rust = ROOT / "code/rust/libs/hal2-plans/src/ledgers"
        for name in ("decisions.md", "questions.md"):
            self.assertEqual((rust / name).read_text(), (HERE.parent / "templates" / name).read_text(), name)


if __name__ == "__main__":
    unittest.main()
