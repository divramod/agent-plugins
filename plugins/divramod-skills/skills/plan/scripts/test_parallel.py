"""plan.py on a parallel plan (skills plan 0013, plan 0016): Needs, Touches, Who, ready, assign, the LEAD refusal."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "plan.py"
SLUG = "0005-big-plan"

PARALLEL = r"""# Plan 0005: big plan

Landing: auto

## Steps

| # | Step | Needs | Touches | Who | Done when | Status |
|---|---|---|---|---|---|---|
| 1 | proto | | proto:core | lead | protos build | done |
| 2 | server a \| b | 1 | rust:server | slot 31 | cargo test | running |
| 3 | client | 1 | ts:client | | npm test | |
| 4 | more server | 1 | rust:server | | cargo test | |
| 5 | vm one | 1 | @vm | | vm up | |
| 6 | vm two | 1 | @vm | | vm up | |
| 7 | vm three | 1 | @vm | | vm up | |
| 8 | Milestone 1: land the server | 2-4 | | lead | main green | |
| 9 | Write the UATs | 1-8 | docs | lead | after the landing: the UATs pass | |
"""

SEQUENTIAL = """# Plan 0001: old plan

| # | Step | Status |
|---|---|---|
| 1 | one | next |
"""


def git(cwd: Path, *args: str, check: bool = True) -> str:
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                         capture_output=True, text=True, check=check)
    return out.stdout


class ParallelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "02"  # the lead's slot
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        self.plans = self.root / "plans"
        self.path = self.write_plan(SLUG, PARALLEL)
        (self.plans / "CURRENT_PLAN").write_text(SLUG + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write_plan(self, slug: str, text: str) -> Path:
        path = self.plans / slug / "plan.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_plan(self, *args, root=None, cwd=None, env=None) -> subprocess.CompletedProcess:
        env = {**os.environ, **(env or {})}
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root or self.root), *args],
                              capture_output=True, text=True, cwd=cwd or self.base, env=env)

    def plan(self, *args, root=None) -> dict:
        result = self.run_plan(*args, root=root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def refused(self, *args, root=None, cwd=None) -> str:
        result = self.run_plan(*args, root=root, cwd=cwd)
        self.assertEqual(result.returncode, 1, result.stdout)
        return result.stderr

    def ready(self, *args) -> dict:
        return self.plan("ready", "--json", *args)

    def numbers(self, steps: list[dict]) -> list[str]:
        return [s["number"] for s in steps]

    def row(self, step: str) -> str:
        return next(l for l in self.path.read_text().splitlines() if l.startswith(f"| {step} |"))

    # the table

    def test_escaped_pipe_is_read_and_written_back(self):
        info = self.plan("current")
        self.assertEqual(info["steps"][1]["step"], "server a | b")
        self.assertTrue(info["parallel"])

        self.plan("status", "2", "done (`abc1234`)")

        self.assertEqual(self.row("2"), r"| 2 | server a \| b | 1 | rust:server | slot 31 | cargo test | done (`abc1234`) |")

    def test_short_row_is_a_clean_error_and_list_keeps_other_plans(self):
        self.write_plan("0006-broken", PARALLEL.replace("| 3 | client | 1 | ts:client | | npm test | |", "| 3 | a | b |"))
        (self.plans / "CURRENT_PLAN").write_text("0006-broken\n")

        error = self.refused("current")
        self.assertIn("row 3 of the step table has 3 cells, its header 7", error)
        self.assertNotIn("Traceback", error)
        plans = {p["slug"]: p for p in self.plan("list")}
        self.assertEqual(plans[SLUG]["total"], 9)
        self.assertIn("row 3", plans["0006-broken"]["problems"][0])

    def test_new_parallel_has_the_columns_and_the_uat_row_needs_every_step(self):
        info = self.plan("new", "more work", "--parallel")

        text = (self.root / info["path"]).read_text()
        self.assertIn("| # | Step | Needs | Touches | Who | Done when | Model | Effort | Window | Size | Status |", text)
        self.assertTrue(info["parallel"])
        uat = info["steps"][-1]
        self.assertEqual((uat["needs"], uat["touches"], uat["who"]), (["1"], ["docs"], "lead"))
        self.assertEqual(info["steps"][0]["needs"], [])
        self.assertEqual(info["problems"], [])

    def test_sequential_plan_has_no_parallel_keys_and_refuses_ready(self):
        self.write_plan("0001-old-plan", SEQUENTIAL)

        info = self.plan("use", "1")
        self.assertNotIn("parallel", info)
        self.assertNotIn("needs", info["steps"][0])
        self.assertIn("is no parallel plan", self.refused("ready"))

    # ready

    def test_ready_honours_needs_touches_and_vm_room(self):
        info = self.ready()

        self.assertEqual(self.numbers(info["ready"]), ["3", "5", "6"])
        self.assertEqual(self.numbers(info["running"]), ["2"])
        why = {w["number"]: w["why"] for w in info["waiting"]}
        self.assertEqual(why["4"], "touches rust:server, in use")
        self.assertEqual(why["7"], "touches @vm, in use")
        self.assertEqual(why["8"], "needs step(s) 2, 3, 4")
        self.assertEqual(why["9"], "checked after the landing")
        self.assertEqual(self.numbers(self.plan("current")["ready"]), ["3", "5", "6"])

    def test_ready_limit_and_plain_output(self):
        self.assertEqual(self.numbers(self.ready("--limit", "1")["ready"]), ["3"])
        self.assertEqual(self.ready("--limit", "1")["waiting"][1]["why"], "the limit of 1 is reached")

        out = self.run_plan("ready").stdout.splitlines()
        self.assertEqual(out[0], "3\tclient\tts:client")
        self.assertEqual(len(out), 3)

    def test_capacity_line_overrides_the_room(self):
        self.path.write_text(PARALLEL.replace("Landing: auto\n", "Landing: auto\n\nCapacity: @vm=3, rust:server=2\n"))

        self.assertEqual(self.numbers(self.ready()["ready"]), ["3", "4", "5", "6", "7"])

    def test_milestones_touch_land_so_only_one_runs(self):
        self.path.write_text(PARALLEL.replace("| 2-4 |", "| 1 |").replace(
            "| 9 | Write the UATs", "| 10 | milestone 2: land the client | 1 | | lead | main green | |\n| 9 | Write the UATs"))

        info = self.ready()
        self.assertIn("@land", info["ready"][-1]["touches"])
        self.assertEqual(self.numbers(info["ready"])[-1], "8")
        self.assertEqual({w["number"]: w["why"] for w in info["waiting"]}["10"], "touches @land, in use")

    def test_done_needs_free_the_waiting_steps(self):
        for step in ("2", "3"):
            self.plan("status", step, "done")

        self.assertEqual(self.numbers(self.ready()["ready"]), ["4", "5", "6"])

    # problems

    def test_problems_name_bad_ids_needs_and_cycles(self):
        self.path.write_text(PARALLEL.replace("| 3 | client | 1 |", "| 3 | client | 4, x |")
                             .replace("| 4 | more server | 1 |", "| 4 | more server | 3, 12 |")
                             .replace("| 6 | vm two |", "| 5 | vm two |")
                             .replace("| 7 | vm three |", "| 7a | vm three |"))

        problems = self.plan("current")["problems"]

        self.assertIn("step 3: Needs 'x' are no step ids or ranges", problems)
        self.assertIn("step 4 needs step(s) 12, which no row has", problems)
        self.assertIn("step id '5' is used twice", problems)
        self.assertTrue(any("'7a' is no integer" in p for p in problems), problems)
        self.assertIn("the Needs form a cycle: 3 -> 4 -> 3", problems)

    # assign

    def test_assign_refuses_a_step_that_is_not_ready_unless_forced(self):
        self.assertIn("step 4 is not ready (touches rust:server, in use)", self.refused("assign", "4", "subagent"))
        self.assertIn("step 2 is not ready (it is running)", self.refused("assign", "2", "lead"))

        info = self.plan("assign", "4", "subagent", "--force")

        self.assertEqual((info["steps"][3]["who"], info["steps"][3]["status"]), ("subagent", "running"))

    def add_slot(self, slot: str) -> Path:
        if not git(self.root, "log", "--oneline", "-1", check=False):
            git(self.root, "commit", "-q", "--allow-empty", "-m", "init")
        git(self.root, "worktree", "add", "-q", "-b", slot, str(self.base / slot))
        return self.base / slot

    def test_assign_takes_lead_subagent_user_and_refuses_a_slot(self):
        before = self.path.read_text()
        for who in (("slot", "33"), ("Slot", "12"), ("slot33",)):
            error = self.refused("assign", "3", *who)
            self.assertIn("run the step as a subagent", error, who)
            self.assertIn("plan.py prompt <step>", error, who)
        self.assertIn("none of lead, subagent, user", self.refused("assign", "3", "bob"))
        self.assertEqual(self.path.read_text(), before)

        info = self.plan("assign", "3", "Subagent")

        self.assertEqual(self.row("3"), "| 3 | client | 1 | ts:client | subagent | npm test | running |")
        self.assertNotIn("marker", info)
        self.assertEqual(self.numbers(info["running"]), ["2", "3"])
        self.assertEqual(info["steps"][1]["who"], "slot 31")  # an older row's slot is still read

    # Touches

    def test_blocked_assigned_step_keeps_its_touches(self):
        self.path.write_text(PARALLEL.replace("| slot 31 | cargo test | running |",
                                              "| slot 31 | cargo test | blocked on the proto |"))
        self.assertEqual({w["number"]: w["why"] for w in self.ready()["waiting"]}["4"], "touches rust:server, in use")

        self.path.write_text(PARALLEL.replace("| slot 31 | cargo test | running |", "| | cargo test | blocked |"))
        self.assertIn("4", self.numbers(self.ready()["ready"]))  # never assigned: holds nothing

    def test_touches_compare_without_backticks_spaces_and_case(self):
        self.path.write_text(PARALLEL.replace("| 1 | @vm |", "| 1 | ` @VM ` |", 1)
                             .replace("| 6 | vm two | 1 | @vm |", "| 6 | vm two | 1 | `@vm`, @Vm |")
                             .replace("| 1 | rust:server | |", "| 1 | Rust: Server | |"))

        info = self.ready()
        self.assertEqual(self.numbers(info["ready"]), ["3", "5", "6"])
        self.assertEqual(info["ready"][1]["touches"], ["@vm"])
        self.assertEqual(info["ready"][2]["touches"], ["@vm"])
        self.assertEqual({w["number"]: w["why"] for w in info["waiting"]}["4"], "touches rust:server, in use")
        capacity = "Landing: auto\n\nCapacity: `@VM` = 3\n"
        self.path.write_text(self.path.read_text().replace("Landing: auto\n", capacity))
        self.assertIn("7", self.numbers(self.ready()["ready"]))

    # the subservant's slot

    def test_a_marked_cwd_refuses_writes_to_the_lead_plan_given_by_root(self):
        slot = self.add_slot("32")
        (slot / "plans").mkdir()
        (slot / "plans" / "LEAD").write_text(f"02 {SLUG} 3\n")
        (slot / "sub").mkdir()
        before = self.path.read_text()

        for args in (("status", "3", "done"), ("assign", "3", "lead")):
            self.assertIn("is a subservant of slot 02", self.refused(*args, cwd=slot / "sub"), args)
        self.assertEqual(self.path.read_text(), before)
        self.assertEqual(self.plan("current")["slug"], SLUG)  # reading works
        self.plan("status", "3", "done")  # from outside the slot the lead writes

    def test_a_marked_slot_refuses_writes_to_the_plan(self):
        before = self.path.read_text()
        (self.plans / "LEAD").write_text(f"02 {SLUG} 3\n")

        for args in (("new", "x"), ("status", "3", "done"), ("assign", "3", "lead"), ("grilled",),
                     ("landing", "manual"), ("uat",), ("scaffold",), ("run", "--effort", "max"), ("migrate",)):
            self.assertIn("is a subservant of slot 02", self.refused(*args), args)
        self.assertEqual(self.path.read_text(), before)
        self.assertEqual(self.plan("current")["lead"], {"slot": "02", "plan": SLUG, "step": "3"})
        self.assertEqual(self.numbers(self.ready()["ready"]), ["3", "5", "6"])

    def test_the_refusal_names_the_stale_marker_and_the_way_out(self):
        (self.plans / "LEAD").write_text(f"07 {SLUG} 3\n")

        error = self.refused("status", "3", "done")

        self.assertIn(f"subservant of slot 07 (plan {SLUG} step 3)", error)
        self.assertIn("stale plans/LEAD of the lead in slot 07", error)
        self.assertIn("never lands", error)
        self.assertIn("delete plans/LEAD", error)
        self.assertNotIn("plan.py report", error)

    def test_removed_commands_are_gone(self):
        for command in ("brief", "report", "reports", "watch"):
            result = self.run_plan(command, "3")
            self.assertEqual(result.returncode, 2, command)
            self.assertIn("invalid choice", result.stderr)

    def test_a_broken_marker_is_a_clean_error(self):
        (self.plans / "LEAD").write_text("02\n")

        self.assertIn("must hold `<lead-slot> <plan> <step>`", self.refused("current"))

    # the step file

    def test_status_next_scaffolds_a_parallel_plans_step_file(self):
        info = self.plan("status", "3", "next")

        self.assertEqual(info["step_file"], f"plans/{SLUG}/steps/3.md")
        self.assertIn("# Step 3: client", (self.root / info["step_file"]).read_text())



if __name__ == "__main__":
    unittest.main()
