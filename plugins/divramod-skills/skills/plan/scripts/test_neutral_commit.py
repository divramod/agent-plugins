"""Neutral commits in the plan skill (hal2 plan 0409 D15, step 11): `planread.neutral` / `link_next` and `plan.py
trailers` / `scope` with the switch on and off. Off (no farm, or the CLI says false, fails or is missing): the output is
what it always was; on: nothing is printed and the next commit's plan link goes to `hal2-cli-plans link-commit --next`."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import neutral_testkit as kit
from neutral_testkit import FakeCli, planread
from shape_testing import TempPlan
from test_trailers import PLAN, SCRIPT


class PlanreadNeutral(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="neutral-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def test_a_checkout_without_a_farm_is_off_and_starts_no_process(self):
        with kit.env(FakeCli(self.tmp)), mock.patch.object(subprocess, "run", side_effect=AssertionError("no process")):
            self.assertFalse(planread.neutral(self.repo))
            self.assertFalse(planread.link_next(self.repo, "0409-plan-store", "3"))

    def test_the_cli_answer_is_read_once_per_root(self):
        kit.farm(self.repo)
        fake = FakeCli(self.tmp)
        with kit.env(fake):
            self.assertTrue(planread.neutral(self.repo))
            self.assertTrue(planread.neutral(self.repo))
        self.assertEqual(fake.calls("commits"), [f"commits --repo {self.repo.resolve()} --json"])

    def test_any_failure_is_off(self):
        kit.farm(self.repo)
        for answer, code in (('{"neutral": false, "why": "default"}', 0), ("not json", 0), ('{"neutral": true}', 3), ("", 0)):
            with self.subTest(answer=answer, code=code), kit.env(FakeCli(self.tmp, answer, code)):
                self.assertFalse(planread.neutral(self.repo))
        with kit.env(None):  # the CLI is missing
            self.assertFalse(planread.neutral(self.repo))

    def test_link_next_names_the_plan_and_step_only_when_neutral(self):
        kit.farm(self.repo)
        on, off = FakeCli(self.tmp), FakeCli(self.tmp / "..", '{"neutral": false, "why": "default"}')
        with kit.env(on):
            self.assertTrue(planread.link_next(self.repo, "0409-plan-store", "3/6", "handoff"))
            self.assertFalse(planread.link_next(self.repo, ""))
        self.assertEqual(on.links(), [f"link-commit --next --plan 0409-plan-store --kind handoff --repo "
                                      f"{self.repo.resolve()} --step 3/6 --json"])
        with kit.env(off):
            self.assertFalse(planread.link_next(self.repo, "0409-plan-store", "3/6"))
        self.assertEqual(off.links(), [])

    def test_link_next_never_raises(self):
        kit.farm(self.repo)
        with kit.env(FakeCli(self.tmp)), mock.patch.object(planread.planhome, "run", side_effect=RuntimeError("boom")):
            self.assertFalse(planread.link_next(self.repo, "0409-plan-store"))

    def test_the_shell_entries(self):
        kit.farm(self.repo)
        fake = FakeCli(self.tmp)
        script = str(Path(planread.__file__))
        env = {**os.environ, "HAL2_CLI_PLANS": str(fake.path)}

        def run(*args):
            return subprocess.run([sys.executable, script, *args, "--root", str(self.repo)], capture_output=True,
                                  text=True, env=env)

        self.assertEqual((run("neutral").returncode, run("neutral").stdout), (0, "on\n"))
        done = run("link-next", "--plan", "0409-plan-store", "--step", "2/5", "--kind", "handoff")
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertIn("--plan 0409-plan-store --kind handoff", fake.links()[0])
        self.assertEqual(subprocess.run([sys.executable, script, "neutral", "--root", str(self.tmp)], capture_output=True,
                                        text=True, env=env).stdout, "off\n")


class TrailersAndScope(unittest.TestCase):
    """Plans of schema 1: `trailers 3` and `scope 3` of test_trailers.py's fixture."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="neutral-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "05"
        (self.root / "plans" / "0355-commit-standards").mkdir(parents=True)
        (self.root / "plans" / "0355-commit-standards" / "plan.md").write_text(PLAN)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        (self.root / "plans" / "CURRENT_PLAN").write_text("0355-commit-standards\n")
        kit.farm(self.root)

    def plan(self, fake, *args):
        env = {**os.environ, "HAL2_CLI_PLANS": str(fake.path) if fake else str(self.tmp / "none")}
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args], capture_output=True,
                              text=True, cwd=self.root, env=env)

    def test_on_trailers_print_nothing_and_link_the_next_commit(self):
        fake = FakeCli(self.tmp)
        done = self.plan(fake, "trailers", "3")

        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)
        self.assertEqual(fake.links(), [f"link-commit --next --plan 0355-commit-standards --kind step --repo "
                                        f"{self.root.resolve()} --step 3/3 --json"])

    def test_on_scope_prints_nothing(self):
        fake = FakeCli(self.tmp)
        done = self.plan(fake, "scope", "3")

        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)
        self.assertEqual(fake.links(), [])

    def test_on_a_bad_step_is_still_refused(self):
        done = self.plan(FakeCli(self.tmp), "trailers", "9")

        self.assertEqual(done.returncode, 1)
        self.assertIn("is no row of plan 0355-commit-standards", done.stderr)

    def test_off_with_a_farm_the_output_is_what_it_was(self):
        fake = FakeCli(self.tmp, '{"neutral": false, "why": "default"}')

        self.assertEqual(self.plan(fake, "trailers", "3").stdout.splitlines(),
                         ["Worktree: 05", "Plan: 0355-commit-standards", "Step: 3/3"])
        self.assertEqual(self.plan(fake, "scope", "3").stdout, "0355|3\n")
        self.assertEqual(fake.links(), [])

    def test_a_missing_cli_is_off(self):
        self.assertEqual(self.plan(None, "scope", "3").stdout, "0355|3\n")


class ShapeTrailers(TempPlan):
    """Plans of schema 2 (shape_cmds.py's routed `trailers`)."""

    def test_on_nothing_is_printed_and_the_step_is_linked(self):
        self.new("deploy the hub")
        kit.farm(self.root)
        fake = FakeCli(self.root.parent)
        self.env["HAL2_CLI_PLANS"] = str(fake.path)

        done = self.run_plan("trailers", "01.02")

        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)
        self.assertEqual(len(fake.links()), 1)
        self.assertIn("--plan 0001-deploy-the-hub --kind step", fake.links()[0])
        self.assertIn("--step 2/2", fake.links()[0])

    def test_on_a_subplan_merge_has_no_trailers_and_no_plan_in_its_subject(self):
        self.new("deploy the hub")
        self.commit_all("plan")
        kit.farm(self.root)
        self.env["HAL2_CLI_PLANS"] = str(FakeCli(self.root.parent).path)
        self.plan("subplan", "start", "1")
        for ref in ("01.01", "01.02"):
            self.plan("status", ref, "done")
        self.commit_all("steps done")

        self.plan("subplan", "finish", "1")

        self.assertEqual(self.git("log", "-1", "--format=%B").strip(), "chore(plans): merge sub-plan 01-deploy-the-hub")

    def test_off_the_three_lines(self):
        self.new("deploy the hub")
        kit.farm(self.root)
        self.env["HAL2_CLI_PLANS"] = str(FakeCli(self.root.parent, '{"neutral": false}').path)

        self.assertEqual(self.run_plan("trailers", "01.02").stdout, "Worktree: 07\nPlan: 0001-deploy-the-hub\nStep: 2/2\n")


if __name__ == "__main__":
    unittest.main()
