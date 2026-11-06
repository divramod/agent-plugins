"""`plan.py finish <ref> [--next <ref>]` (hal2 plan 0485 step 03.01): a step boundary in one call and one JSON, on a
plan of schema 1 and of schema 2, a plan of a masterplan (its row ticked), a sub-plan servant's field and the store
home. Every test works in a scratch repository with a scratch transcript and HOME; none needs hal2 but the store
home's (skipped without a hal2-cli-plans that has it)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import envelope
import shape
import testkit
import test_masterplan as base
import servant_testkit  # on the path once test_masterplan is imported
from shape_testing import TempPlan
from store_testkit import DEBUG, StoreFarm

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "plan.py"
SESSION = "finish-test"


def transcript(home: Path, used: int, model: str = "claude-sonnet-5-5[1m]", effort: str = "low") -> Path:
    """The session's transcript under `home` (its id `SESSION`), one call: `used` tokens in context, the session's
    model and effort (so nothing asks the process table, which is slow on a loaded Mac)."""
    path = home / ".claude/projects/scratch" / f"{SESSION}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    usage = {"input_tokens": 10, "cache_read_input_tokens": used - 10, "output_tokens": 0}
    path.write_text(json.dumps({"type": "assistant", "requestedModel": model, "effort": effort,
                                "message": {"usage": usage}}) + "\n")
    return path


def quiet_env(home: Path) -> dict:
    """No hal2 CLI, a scratch session: its transcript under the scratch HOME is the only source, nothing of the
    user's is read."""
    missing = str(home / "no-such-binary")
    transcript(home, 100_000)
    ps = home / "bin" / "ps"  # an empty process table: no `claude` above, the session running the tests never counts
    ps.parent.mkdir(exist_ok=True)
    ps.write_text("#!/bin/sh\n")
    ps.chmod(0o755)
    return {**os.environ, "HOME": str(home), "PATH": f"{ps.parent}{os.pathsep}{os.environ.get('PATH', '')}",
            "CLAUDE_CODE_SESSION_ID": SESSION, "HAL2_CLI_RECORDS": missing,
            "HAL2_CLI_PLANS": missing, "HAL2_CLI_AGENTS": missing, shape.CLI_ENV: missing}


class SchemaOne(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "05"
        self.root.mkdir()
        testkit.init_repo(self.root, "05")
        self.env = quiet_env(Path(self.tmp.name))
        self.plan("new", "demo plan", "--goal", "x", "--schema", "1")
        self.file = self.root / "plans/0001-demo-plan/plan.md"
        self.file.write_text(self.file.read_text().replace(
            "| 2 | Write the UATs", "| 2 | wire it | a check | opus | high | 1m | 120k | |\n| 3 | Write the UATs"))

    def tearDown(self):
        self.tmp.cleanup()

    def run_plan(self, *args) -> subprocess.CompletedProcess:
        return testkit.run(SCRIPT, ["--root", str(self.root), *args], env=self.env, cwd=self.root)

    def plan(self, *args) -> dict:
        result = self.run_plan(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def finish(self, *args, used: int = 100_000) -> dict:
        transcript(Path(self.tmp.name), used)
        return self.plan("finish", *args)

    def status(self, number: str) -> str:
        return next(s["status"] for s in self.plan("current")["steps"] if s["number"] == number)

    def test_one_call_marks_done_and_next_and_prints_scope_trailers_run_and_context(self):
        info = self.finish("1", "--next", "2")
        self.assertEqual((self.status("1"), self.status("2")), ("done", "next"))
        self.assertEqual(info["next"]["step_file"], "plans/0001-demo-plan/steps/2.md")
        self.assertTrue((self.root / info["next"]["step_file"]).is_file())
        self.assertEqual(info["scope"], "0001|1")
        self.assertEqual(info["trailers"], ["Worktree: 05", "Plan: 0001-demo-plan", "Step: 1/3"])
        self.assertEqual(info["run"]["run"], "claude-sonnet-5-5 low 1m", "run --sync took the transcript's values")
        self.assertEqual(envelope.get(self.file.read_text(), "run"), "claude-sonnet-5-5 low 1m")
        self.assertEqual((info["context"]["known"], info["context"]["percent"], info["stop"]), (True, 12.0, False))
        self.assertEqual((info["done"], info["total"], info["upcoming"]["number"], info["land"]), (1, 3, "2", "wait"))

    def test_stop_says_hand_off_above_the_threshold(self):
        self.assertTrue(self.finish("1", used=400_000)["stop"])
        self.assertTrue(self.finish("2", "--threshold", "5")["stop"])

    def test_a_bad_ref_writes_nothing(self):
        before = self.file.read_text()
        for args in (("9",), ("1", "--next", "9"), ("1", "--next", "1")):
            result = self.run_plan("finish", *args)
            self.assertEqual(result.returncode, 1, args)
            self.assertEqual(self.file.read_text(), before, args)

    def test_without_a_transcript_the_context_is_unknown(self):
        transcript(Path(self.tmp.name), 1).unlink()
        info = self.plan("finish", "1", "--transcript", str(Path(self.tmp.name) / "none.jsonl"))
        self.assertEqual((info["context"]["known"], info["stop"], info["next"]), (False, None, None))

    def test_a_legacy_servant_is_refused(self):
        (self.root / "plans/LEAD").write_text("04 0001-demo-plan 1\n")
        self.assertIn("finish", self.run_plan("finish", "1").stderr)


class SchemaTwo(TempPlan):
    def setUp(self):
        super().setUp()
        self.env = quiet_env(Path(self.tmp.name))

    def finish(self, *args) -> dict:
        return self.plan("finish", *args)

    def test_step_files_overview_trailers_and_run_in_one_call(self):
        folder = self.new("deploy the hub")
        info = self.finish("01.01", "--next", "01.02", "--why", "it ran")
        self.assertEqual((info["schema"], info["step"]["ref"], info["next"]["ref"], info["overview"]),
                         (2, "01.01", "01.02", "shape.py"))
        self.assertIn("why: it ran\n", (folder / "subplans/01-deploy-the-hub/steps/step-01.md").read_text())
        self.assertIn("status: next\n", (folder / "subplans/01-deploy-the-hub/steps/step-02.md").read_text())
        self.assertEqual(shape.check_overview(folder), [])
        self.assertEqual((info["scope"], info["trailers"][2]), ("0001|01.01", "Step: 1/2"))
        self.assertEqual(envelope.get((folder / "plan.md").read_text(), "run"), "claude-sonnet-5-5 low 1m")
        self.assertEqual((info["done"], info["upcoming"]["number"], info["plan_status"]), (1, "01.02", "open"))
        self.assertIn("no ref", self.refused("finish", "1"))

    def test_the_last_step_finishes_the_plan(self):
        folder = self.new("deploy the hub")
        self.finish("01.01", "--next", "01.02")
        info = self.finish("01.02")
        self.assertEqual((info["done"], info["total"], info["land"], info["plan_status"]), (2, 2, "ready", "done"))
        self.assertTrue(envelope.get((folder / "plan.md").read_text(), "finished"))

    def test_a_sub_plan_servant_marks_its_steps_and_leaves_run_and_the_overview(self):
        self.env["HAL2_CLI_PLANS"] = str(servant_testkit.install(self))  # the fake `servant show` (plan 0594)
        folder = self.new("deploy the hub")
        before = (folder / "plan.md").read_text()
        (self.root / "plans/LEAD").write_text("05 0001-deploy-the-hub 01-deploy-the-hub\n")
        info = self.finish("01.01", "--next", "01.02")
        self.assertIn("servant", info["run"]["skipped"])
        self.assertIn("servant", info["overview"])
        self.assertEqual((folder / "plan.md").read_text(), before, "plan.md is the foreman's")


class MasterplanTick(unittest.TestCase):
    """test_masterplan.py's scratch farm, its helpers borrowed (not its tests)."""
    tearDown = base.MasterplanTest.tearDown
    run_plan, plan, farm = base.MasterplanTest.run_plan, base.MasterplanTest.plan, base.MasterplanTest.farm

    def setUp(self):
        base.MasterplanTest.setUp(self)
        quiet = mock.patch.dict(os.environ, quiet_env(self.base))  # its run_plan starts from os.environ
        quiet.start()
        self.addCleanup(quiet.stop)

    def finish(self, *args) -> dict:
        result = testkit.run(SCRIPT, ["--root", str(self.root), "finish", *args], cwd=self.base,
                             env=quiet_env(self.base))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def row(self, master: Path) -> str:
        line = next(l for l in master.read_text().splitlines() if l.startswith("| 1 | ["))
        return line.rstrip(" |").rsplit("|", 1)[1].strip()

    def test_the_plans_last_step_ticks_its_masterplan_row(self):
        master = self.farm()  # 0002-tools (schema 1) is the current plan and the masterplan's row 1
        self.assertNotIn("tick", self.finish("1", "--next", "2"))
        info = self.finish("2")
        self.assertEqual(info["tick"], {"masterplan": base.MASTER, "row": "1", "status": "done",
                                        "masterplan_finished": True})
        self.assertEqual(info["scope"], "0001|0002|2")
        self.assertEqual(self.row(master), "done")

    def test_a_schema_2_plan_ticks_its_row_too(self):
        self.plan("new", "Masterplan farm view", "--masterplan")
        self.plan("new", "tools", "--parent", "1", "--schema", "2")
        master = self.plans / base.MASTER / "plan.md"
        self.assertNotIn("tick", self.finish("01.01", "--next", "01.02"))
        info = self.finish("01.02")
        self.assertEqual((info["tick"]["row"], info["tick"]["status"]), ("1", "done"))
        self.assertEqual(self.row(master), "done")


@unittest.skipUnless(DEBUG, "no hal2-cli-plans with the store home")
class StoreHome(StoreFarm, unittest.TestCase):
    def test_finish_works_on_the_store_and_leaves_the_tree_clean(self):
        transcript(Path(os.environ["HOME"]), 100_000)
        os.environ.update(CLAUDE_CODE_SESSION_ID=SESSION, HAL2_CLI_AGENTS=str(self.tmp / "no-such-binary"))
        self.run_ok(sys.executable, str(SCRIPT), "new", "Store run", "--goal", "x", "--schema", "1")
        info = json.loads(self.run_ok(sys.executable, str(SCRIPT), "finish", "1", "--next", "2"))
        self.assertEqual((info["done"], info["upcoming"]["number"]), (1, "2"))
        self.assertEqual(info["next"]["step_file"], "plans/0001-store-run/steps/2.md")
        steps = self.cli("show", "1")["steps"]
        self.assertEqual([s["status"] for s in steps[:2]], ["done", "next"])
        self.assertEqual(info["run"]["run"], "claude-sonnet-5-5 low 1m")
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
