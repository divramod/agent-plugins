import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import lead_marker
import lead_scan as lead
import test_prune
from test_farmer import git


def agent(**over):
    base = {"state": "done", "since": int((time.time() - 3600) * 1000), "plan": "", "context_percent": 20}
    base.update(over)
    return base


class Classify(unittest.TestCase):
    def test_a_question_to_the_user_needs_help(self):
        self.assertEqual(lead.classify(agent(), "Which option do you want?", time.time())[0], "asks")
        self.assertEqual(lead.classify(agent(), "AskUserQuestion: Land now?", time.time())[0], "asks")
        self.assertEqual(lead.classify(agent(), "Waiting for the user to unlock the Mac.", time.time())[0], "asks")

    def test_a_finished_report_outside_a_plan_needs_none(self):
        self.assertIsNone(lead.classify(agent(), "Done. All tests pass.", time.time()))

    def test_idle_inside_a_plan_and_blocked_dialogs(self):
        self.assertEqual(lead.classify(agent(plan="0094 n8n"), "Step 6 done.", time.time())[0], "idle-in-plan")
        fresh = agent(state="blocked", since=int(time.time() * 1000))
        self.assertIsNone(lead.classify(fresh, "", time.time()))
        self.assertEqual(lead.classify(agent(state="blocked"), "", time.time())[0], "blocked")

    def test_a_coordinator_waiting_on_its_subagents_is_not_idle_in_plan(self):
        # Skills plan 0016 (D14): idle while background subagents run is a plan's normal state.
        tasks = [{"id": "a1", "type": "subagent", "description": "Plan 0094 row 6: n8n"}]
        self.assertIsNone(lead.classify(agent(plan="0094 n8n", background_tasks=tasks), "Step 6 runs.", time.time()))
        ended = [dict(tasks[0], status="completed")]
        self.assertEqual(lead.classify(agent(plan="0094 n8n", background_tasks=ended), "", time.time())[0],
                         "idle-in-plan")
        asks = agent(plan="0094 n8n", background_tasks=tasks)
        self.assertEqual(lead.classify(asks, "Which option do you want?", time.time())[0], "asks")

    def test_a_working_session_needs_help_only_near_its_context_limit(self):
        self.assertIsNone(lead.classify(agent(state="working"), "Should I?", time.time()))
        self.assertEqual(lead.classify(agent(state="working", context_percent=91), "", time.time())[0],
                         "context-high")


    def test_a_working_slot_without_current_plan_is_told_to_fill_it(self):
        self.assertEqual(lead.classify(agent(state="working", slot="07"), "", time.time())[0], "no-plan")
        self.assertIsNone(lead.classify(agent(state="working", slot="07", current_plan="0094-n8n"), "", time.time()))
        self.assertIsNone(lead.classify(agent(state="working", slot="main"), "", time.time()))


LEAD = {"slot": "02", "plan": "0149-hal9k", "step": "7"}


class Subservant(unittest.TestCase):
    """Skills plan 0013: a slot with plans/LEAD runs one step of its lead's plan and never lands."""

    def test_a_marked_slot_idle_mid_step_is_idle_in_plan_even_without_a_plan(self):
        kind, why = lead.classify(agent(slot="31", lead=LEAD), "Step done.", time.time())
        self.assertEqual(kind, "idle-in-plan")
        self.assertIn("subservant of slot 02 (plan 0149-hal9k step 7)", why)
        self.assertEqual(lead.classify(agent(slot="31", lead=LEAD), "Should I?", time.time())[0], "asks")
        fresh = agent(slot="31", lead=LEAD, since=int(time.time() * 1000))
        self.assertIsNone(lead.classify(fresh, "Step done.", time.time()))

    def test_a_subservant_done_with_its_step_waits_for_its_lead_and_wakes_nobody(self):
        # Review 1 finding 12: its report on origin/NN or its HEAD in origin/<lead>: no hourly wake.
        done = agent(slot="31", lead=LEAD, step_done=True)
        self.assertIsNone(lead.classify(done, "Step 7 reported. Waiting for the lead?", time.time()))
        self.assertEqual(lead.classify(dict(done, state="blocked"), "", time.time())[0], "blocked")
        bad = {"bad": True, "text": "x", "error": "plans/LEAD is not `<lead-slot> <plan> <step>`: 'x'"}
        kind, why = lead.classify(agent(slot="31", lead=bad), "Step done.", time.time())
        self.assertEqual(kind, "idle-in-plan")
        self.assertIn("broken marker", why)

    def test_the_scan_reads_each_sessions_marker(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "31/plans").mkdir(parents=True)
            (Path(d) / "31/plans/LEAD").write_text("02 0149-hal9k 7\n")
            (Path(d) / "04").mkdir()
            agents = [agent(project="/x/hal2", session_id=f"s{s}", slot=s, checkout=str(Path(d) / s), pane_id=f"%{s}")
                      for s in ("31", "04")]
            with mock.patch.object(lead, "run_json", return_value=agents), \
                    mock.patch.object(lead, "main_checkout", return_value="/x/hal2"), \
                    mock.patch.object(lead, "handled", return_value=set()), \
                    mock.patch.object(lead, "PROJECTS", Path(d) / "projects"):
                got = lead.scan(d, False)["needs_help"]
        self.assertEqual([(h["slot"], h["kind"], h["lead"]) for h in got], [("31", "idle-in-plan", LEAD)])


class Transcript(unittest.TestCase):
    def test_the_last_assistant_text_or_question_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            rows = [
                {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "old"}]}},
                {"type": "user", "message": {"role": "user", "content": "go"}},
                {"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "AskUserQuestion",
                     "input": {"questions": [{"question": "Land now?"}]}}]}},
            ]
            p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            self.assertEqual(lead.last_assistant_text(p), "AskUserQuestion: Land now?")
            self.assertEqual(lead.last_assistant_text(Path(d) / "missing.jsonl"), "")

    def test_the_transcript_path_munges_the_cwd(self):
        self.assertTrue(str(lead.transcript("/Users/mod/.hal/git/worktree/hal2/04", "x")).endswith(
            "-Users-mod--hal-git-worktree-hal2-04/x.jsonl"))


class StepDone(test_prune.MarkedSlots):
    """Review 1 finding 12: lead_marker.step_done on real slots (lead 02, plan 0013-parallel-plans, step 4).
    31: merged into origin/02 without a report; 32: not merged."""

    REPORT = "plans/0013-parallel-plans/reports/4.md"

    def report(self, name):
        path = self.base / name
        (path / self.REPORT).parent.mkdir(parents=True, exist_ok=True)
        (path / self.REPORT).write_text("# report\n")
        git(path, "add", self.REPORT)
        git(path, "commit", "-q", "-m", "report step 4")
        git(path, "push", "-q", "origin", name)

    def done(self, name):
        path = self.base / name
        return lead_marker.step_done(path, name, lead_marker.marker(path))

    def test_the_report_on_origin_nn_finishes_the_step(self):
        self.assertFalse(self.done("32"))
        self.report("32")
        self.assertTrue(self.done("32"))

    def test_head_in_the_leads_branch_finishes_it_only_with_the_report(self):
        self.assertFalse(self.done("31"), "merged, but no report: a fresh slot's HEAD is in origin/02 too")
        self.report("31")
        git(self.lead, "merge", "-q", "--no-ff", "-m", "merge 31", "origin/31")
        git(self.lead, "push", "-q", "origin", "02")
        git(self.main, "push", "-q", "origin", "--delete", "31")  # prune deletes origin/NN
        git(self.main, "fetch", "-q", "--prune", "origin")
        self.assertTrue(self.done("31"))

    def test_the_scan_leaves_a_finished_subservant_alone(self):
        agents = [agent(project="/x/hal2", session_id="s32", slot="32", checkout=str(self.base / "32"),
                        pane_id="%32")]
        with mock.patch.object(lead, "run_json", return_value=agents), \
                mock.patch.object(lead, "main_checkout", return_value="/x/hal2"), \
                mock.patch.object(lead, "handled", return_value=set()), \
                mock.patch.object(lead, "PROJECTS", self.tmp / "projects"):
            self.assertEqual([h["kind"] for h in lead.scan(str(self.main), False)["needs_help"]], ["idle-in-plan"])
            self.report("32")
            self.assertEqual(lead.scan(str(self.main), False)["needs_help"], [])


if __name__ == "__main__":
    unittest.main()
