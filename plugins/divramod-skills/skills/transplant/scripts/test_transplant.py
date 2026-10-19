#!/usr/bin/env python3
"""Tests for transplant.py with fake hal2 CLIs on PATH and a fake login shell (nothing real is started or stopped)."""
import importlib.util
import sys
import unittest
from pathlib import Path

from test_support import HERE, OK, Scratch

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import unit_root  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

# D6's words and `not-prepared`: every refusal the CLI's JSON can carry.
REASONS = ("same", "main", "role", "no-source", "servant", "nothing", "off-branch", "dirty", "at-the-gate",
           "target-taken", "target-busy", "conflict", "side-branch", "prepared-elsewhere", "not-prepared")
GATE = unit_root(__file__) / "scripts" / "check-agent-starts.py"


def refused(reason, rc=14):  # a refusal exits 14 (7 before hal2 plan 0318 row 22): the skill reads the JSON only
    return [rc, {"status": "refused", "transplant": None, "refused": {"reason": reason, "detail": f"{reason}!",
                                                                    "files": ["a.txt"]}, "checks": [], "would": None}]


class TestCheck(Scratch):
    def names(self):
        return [" ".join(c[1:-1][:4]) for c in self.calls() if c[0] == "hal2-cli-git"]

    def test_clean_dry_run_from_the_foremans_own_field(self):
        code, result, _ = self.run_script("check", "09", repo=self.f34)
        self.assertEqual(code, 0, result)
        self.assertEqual((result["ok"], result["from"], result["to"], result["own"]), (True, "34", "09", "34"))
        self.assertEqual(self.names(), ["--help", "worktree transplant 34 09"])
        self.assertIn("--dry-run", self.calls()[-1])

    def test_a_cli_without_the_command_stops_before_anything_else(self):
        self.config(help="usage: hal2-cli-git worktree run\n", transplant={"dry-run": [0, OK]})
        code, result, _ = self.run_script("check", "09", repo=self.f34)
        self.assertEqual((code, result["stop"]), (1, "no-command"))
        self.assertEqual(self.names(), ["--help"])
        self.assertIn("tell the user", result["advice"])

    def test_every_refusal_word_ends_with_its_reason_and_a_way_out(self):
        for reason in REASONS:
            self.config(transplant={"dry-run": refused(reason)})
            code, result, _ = self.run_script("check", "09", repo=self.f34)
            self.assertEqual((code, result["stop"], result["reason"]), (1, "refused", reason), reason)
            self.assertTrue(result["advice"] and "{" not in result["advice"], reason)
            self.assertEqual(result["files"], ["a.txt"])

    def test_a_clean_dry_run_that_failed_is_an_error(self):
        self.config(transplant={"dry-run": [1, {"status": "error", "message": "git failed", "transplant": None}]})
        code, result, _ = self.run_script("check", "09", repo=self.f34)
        self.assertEqual((code, result["stop"], result["message"]), (1, "error", "git failed"))

    def test_a_foreign_source_with_a_live_session_is_never_driven(self):
        self.sessions(("34", {}))
        code, result, _ = self.run_script("check", "34", "09")  # from the yard (the steward or the farmer)
        self.assertEqual((code, result["stop"]), (1, "live-session"))
        self.assertIn("/transplant 09", result["advice"])
        self.assertEqual(self.names(), ["--help"])  # the dry run never ran

    def test_the_foremans_own_session_is_no_obstacle_and_a_foreign_source_without_one_is_fine(self):
        self.sessions(("34", {}))
        self.assertEqual(self.run_script("check", "09", repo=self.f34)[0], 0)
        self.sessions()
        code, result, _ = self.run_script("check", "34", "09")
        self.assertEqual((code, result["from"], result["own"]), (0, "34", "app"))

    def test_without_a_numbered_field_the_source_must_be_named(self):
        code, result, _ = self.run_script("check", "09")
        self.assertEqual((code, result["stop"]), (1, "call"))

    def test_a_missing_tool_exits_2_naming_it(self):
        code, _, err = self.run_script("check", "09", repo=self.f34, path_dirs=[str(self.bin / "none")])
        self.assertEqual(code, 2)
        self.assertIn("is missing", err)

    def test_numbers_are_padded(self):
        _, result, _ = self.run_script("check", "9", repo=self.f34)
        self.assertEqual(result["to"], "09")
        self.assertIn("34 09", " ".join(self.calls()[-1]))


class TestCheckDisk(Scratch):
    with_target = False

    def test_a_target_to_be_created_needs_free_disk(self):
        code, result, _ = self.run_script("check", "09", "--min-free-gb", "100000000", repo=self.f34)
        self.assertEqual((code, result["stop"]), (1, "disk"))
        self.assertEqual(sum(1 for c in self.calls() if c[1:3] == ["worktree", "transplant"]), 0)
        code, result, _ = self.run_script("check", "09", "--min-free-gb", "0", repo=self.f34)
        self.assertEqual(code, 0, result)


class TestFree(Scratch):
    def test_no_session_in_the_target_stops_nothing(self):
        code, result, _ = self.run_script("free", "34", "09", repo=self.f34)
        self.assertEqual((code, result), (0, {"freed": True, "stopped": []}))
        self.assertFalse([c for c in self.calls() if c[:2] == ["hal2-cli-agents", "stop"]])

    def test_an_idle_session_is_stopped_by_signal_through_stop_py(self):
        self.sessions(("09", {}), ("34", {}))
        code, result, _ = self.run_script("free", "34", "09", repo=self.f34)
        self.assertEqual((code, result), (0, {"freed": True, "stopped": ["t:s09"]}))
        stops = [c for c in self.calls() if c[:2] == ["hal2-cli-agents", "stop"]]
        self.assertEqual([c[2] for c in stops], ["t:s09"])

    def test_a_refused_stop_cancels_the_transplant(self):
        self.sessions(("09", {}))
        (self.fake / "refuse-stop").write_text("")
        self.config(transplant={"cancel": [0, {"status": "ok", "transplant": {"state": "cancelled"}}]})
        code, result, _ = self.run_script("free", "34", "09", repo=self.f34)
        self.assertEqual(code, 3)
        self.assertEqual((result["freed"], result["cancelled"]), (False, True))
        self.assertIn("draft", result["refused"])
        self.assertEqual(self.calls()[-1][1:5], ["worktree", "transplant", "34", "--cancel"])


class TestStart(Scratch):
    def plan(self, run="run: claude-opus-5-5 high 1m"):
        (self.f09 / "plans" / "0286-demo").mkdir(parents=True)
        (self.f09 / "plans" / "CURRENT_PLAN").write_text("0286-demo\n")
        (self.f09 / "plans" / "0286-demo" / "plan.md").write_text(f"---\ntype: Plan\n{run}\n---\n# Plan\n")

    def history(self, state):
        self.config(transplants=[{"from": "34", "to": "09", "state": state}, {"from": "34", "to": "07", "state": "arrived"}])

    def runs(self):
        return [c for c in self.calls() if c[1:3] == ["worktree", "run"]]

    def test_no_start_when_the_drive_was_refused(self):
        for state in ("prepared", "cancelled"):
            self.history(state)
            code, result, _ = self.run_script("start", "09", repo=self.f34)
            self.assertEqual((code, result["stop"]), (1, "not-driven"), state)
        self.config(transplants=[])
        self.assertEqual(self.run_script("start", "09", repo=self.f34)[0], 1)
        self.assertEqual(self.runs(), [])

    def test_the_foreman_starts_with_handoff_c_at_the_plans_model_and_effort(self):
        self.plan()
        self.history("arrived")
        code, result, err = self.run_script("start", "09", repo=self.f34)
        self.assertEqual(code, 0, err)
        self.assertEqual((result["started"], result["slot"], result["effort"]), (True, "09", "high"))
        (call,) = self.runs()
        self.assertEqual(call[1:], ["worktree", "run", "09", "--agent", "claude", "--detach", "--json", "--model",
                                    "claude-opus-5-5[1m]", "--effort", "high", "--prompt", "/handoff c", "TMUX="])

    def test_a_model_alias_without_a_window_and_a_driven_record(self):
        self.plan("run: sonnet medium")
        self.history("driven")
        self.assertEqual(self.run_script("start", "09", repo=self.f34)[0], 0)
        self.assertEqual(self.runs()[0][8:12], ["--model", "sonnet", "--effort", "medium"])

    def test_a_task_name_instead_of_a_plan_starts_at_the_agents_defaults(self):
        (self.f09 / "plans").mkdir()
        (self.f09 / "plans" / "CURRENT_PLAN").write_text("transplant-from-34\n")
        self.history("arrived")
        self.assertEqual(self.run_script("start", "09", repo=self.f34)[0], 0)
        self.assertNotIn("--model", self.runs()[0])

    def test_a_session_already_in_the_target_is_left_and_named(self):
        self.history("arrived")
        self.sessions(("09", {}))
        code, result, _ = self.run_script("start", "09", repo=self.f34)
        self.assertEqual((code, result["started"], result["left"]), (0, False, "t:s09"))
        self.assertEqual(self.runs(), [])


class TestAdviceAndStarts(unittest.TestCase):
    def test_every_word_has_advice_that_says_run_again_or_its_own_way_out(self):
        import transplant
        for reason in REASONS + ("error",):
            text = transplant.advice(reason, "34", "09")
            self.assertTrue(text and "{" not in text, reason)
            self.assertNotIn("reset", text.replace("restock", ""), reason)  # never "reset a field by hand" (D33)
        self.assertIn("same command again", transplant.advice("dirty"))
        # The open transplant's command is the CLI's to name: `<from> --cancel` built from this call's field fails
        # where that field is the other transplant's target, and a half-driven one is finished, never cancelled.
        self.assertNotIn("transplant 34 --cancel", transplant.advice("prepared-elsewhere", "34", "09"))
        self.assertIn("finishes it", transplant.advice("not-prepared", "34", "09"))

    def test_the_advice_call_prints_a_line(self):
        import subprocess
        import sys
        r = subprocess.run([sys.executable, "-B", str(HERE / "transplant.py"), "advice", "conflict", "34", "9"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("field 34", r.stdout)

    def test_no_script_starts_an_agent_or_types_exit(self):
        spec = importlib.util.spec_from_file_location("gate", GATE)
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        for script in HERE.glob("*.py"):
            if not script.name.startswith("test_"):
                self.assertEqual(gate.starts(script.name, script.read_text()), [], script.name)


if __name__ == "__main__":
    unittest.main()
