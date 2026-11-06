"""`/s` busy detection and the plan run state (hal2 plan 0514 step 3, D4, D7, D16): a session with background work is
busy, a field maps to its session by checkout path, and the State cell carries the run state and the workqueue wait."""

import os
import unittest

import state
import state_run
import state_table
import test_state
import view_farmer
import view_foreman

REAL = os.path.realpath
SHELL = {"type": "shell", "status": "running", "alive": True}


def status_doc(**kw) -> dict:
    return {"running": [], "waiting": [], "holds": [], "frozen": [], "live": [], **kw}


class Busy(test_state.Fixture):
    def agent_of(self, field: str, **agent) -> dict:
        self.mock(state.src, "agents", lambda: {REAL(self.wt / field): agent})
        return self.rows()[field]

    def test_a_done_session_with_a_background_shell_is_busy(self):
        row = self.agent_of("02", state="done", background_tasks=[SHELL])
        self.assertEqual((row["agent"], row["agent_state"]), ("busy", "done"))
        self.assertIn("busy", row["cells"][3])

    def test_a_blocked_session_is_busy(self):
        self.assertEqual(self.agent_of("02", state="blocked")["agent"], "busy")

    def test_an_ended_background_task_does_not_count(self):
        ended = [{"type": "shell", "status": "completed"}, {"type": "subagent", "alive": False}]
        self.assertEqual(self.agent_of("02", state="done", background_tasks=ended)["agent"], "idle")
        self.assertEqual(self.agent_of("02", state="sleeping")["agent"], "idle")

    def test_a_field_maps_to_its_session_by_checkout_never_by_name(self):
        """D16: another repository's field 02 (same number, another folder) is not this repository's field 02."""
        other = [{"kind": "claude", "checkout": str(self.tmp / "jobsearch/02"), "state": "working", "pane_id": "%9"}]
        self.mock(state.src, "tool_json", lambda args, cwd=None: {"agents": other})
        self.mock(state.src, "agents", lambda real=state.src.agents: None)
        got = test_state.REAL["agents"]()
        self.assertEqual(list(got), [REAL(self.tmp / "jobsearch/02")])
        self.mock(state.src, "agents", lambda: got)
        self.assertEqual(self.rows()["02"]["agent"], "none")


REAL_STATUS = state.src.autopilot_status  # the real reader, before a Fixture mocks it


class RunState(test_state.Fixture):
    def set_state(self, field: str, state_word: str, why: str | None = None, plan: str = "0042-the-answer") -> None:
        state_run.runstate.write(self.wt / field, plan, state_word, why)

    def set_queue(self, doc: dict | None) -> None:
        self.mock(state.src, "workqueue_status", lambda: doc)
        self.mock(state.src, "workqueue_jobs", lambda raw=None: (raw or {}).get("live"))

    def test_pushing_with_a_hold_shows_what_it_waits_behind(self):
        self.set_state("02", "pushing")
        self.set_queue(status_doc(
            waiting=[{"field": "wt/02", "class": "build", "cwd": str(self.wt / "02")}],
            holds=[{"id": "h1", "class": "landing", "field": "proj/07", "state": "holding"}]))
        row = self.rows()["02"]
        self.assertEqual((row["run_state"]["state"], row["wq_wait"]), ("pushing", "waits behind landing 07"))
        self.assertIn("pushing, waits behind landing 07", row["cells"][3])
        data = state.collect(str(self.main))
        self.assertIn("pushing, waits behind landing 07", state_table.table(data))

    def test_waiting_and_blocked_carry_their_why(self):
        self.set_state("02", "waiting", "the answer to Q3")
        self.assertIn("waiting (the answer to Q3)", self.rows()["02"]["cells"][3])
        self.set_state("02", "blocked", "CI is red")
        self.assertIn("blocked (CI is red)", self.rows()["02"]["cells"][3])

    def test_every_other_state_is_its_word(self):
        for word in ("working", "done", "hitched", "landed"):
            self.set_state("02", word)
            self.assertIn(word, self.rows()["02"]["cells"][3])

    def test_a_field_without_a_file_or_with_another_plans_file_has_no_run_state(self):
        self.assertIsNone(self.rows()["02"]["run_state"])
        self.set_state("02", "working", plan="0001-old-plan")
        self.assertIsNone(self.rows()["02"]["run_state"])

    def test_the_jobs_table_and_the_waits_come_from_one_read(self):
        reads = []
        self.mock(state.src, "workqueue_status", lambda: reads.append(1) or status_doc(live=[{"field": "wt/02", "head": "cargo"}]))
        self.mock(state.src, "workqueue_jobs", test_state.REAL_JOBS)
        data = state.collect(str(self.main))
        self.assertEqual((len(reads), [j["field"] for j in data["jobs"]]), (1, ["wt/02"]))

    def test_status_the_cause_comes_from_the_cli_text_before_any_wait(self):
        """Plan 0695 D14: a frozen field says the autopilot CLI's own `text`; a field it does not name keeps its wait."""
        self.set_queue(status_doc(waiting=[{"field": "wt/10", "class": "build", "cwd": str(self.wt / "10")}],
                                  holds=[{"id": "h1", "class": "landing", "field": "proj/07", "state": "holding"}]))
        self.mock(state.src, "autopilot_status", lambda main: {"02": "frozen by CI (divramod-hal2-a)", "1": "thawed by CI"})
        rows = self.rows()
        self.assertEqual(rows["02"]["wq_wait"], "frozen by CI (divramod-hal2-a)")
        self.assertIn("frozen by CI (divramod-hal2-a)", rows["02"]["cells"][3])
        self.assertEqual(rows["10"]["wq_wait"], "waits behind landing 07")
        self.assertEqual(rows["1"]["wq_wait"], "thawed by CI")

    def test_status_the_cli_document_is_read_as_field_to_text(self):
        doc = {"schema": 1, "repo": "hal2", "fields": [{"field": "07", "status": "frozen_user", "detail": "x", "text": "frozen by user"},
                                                       {"field": "", "text": "no"}, "junk"]}
        self.mock(state.src, "tool_json", lambda args, cwd=None: doc)
        self.assertEqual(REAL_STATUS(str(self.main)), {"07": "frozen by user"})
        self.mock(state.src, "tool_json", lambda args, cwd=None: None)
        self.assertIsNone(REAL_STATUS(str(self.main)))

    def test_the_pages_show_it(self):
        row = {**view_farmer.DEFAULTS, "wt": "02", "paused": None, "run_state": {"state": "pushing", "why": "", "at": ""},
               "wq_wait": "waits behind landing 07"}
        self.assertIn("pushing, waits behind landing 07", view_farmer.state_cell(row, False))
        self.assertEqual(view_foreman.run_line(row), "Run state: pushing, waits behind landing 07")
        self.assertEqual(view_foreman.run_line({**row, "run_state": None, "wq_wait": None}), "")


class Waits(unittest.TestCase):
    FIELD = "/h/.hal/git/worktree/hal2/02"

    def test_waiting_job_names_the_holder_by_class_and_field(self):
        doc = status_doc(waiting=[{"field": "hal2/02", "class": "build"}],
                         holds=[{"id": "a", "class": "smuggle", "field": "hal2/16", "state": "holding"}])
        self.assertEqual(state_run.wait_of(doc, self.FIELD), "waits behind smuggle 16")

    def test_without_a_holder_a_running_job_of_another_field_is_named(self):
        doc = status_doc(waiting=[{"field": "hal2/02", "class": "build"}],
                         running=[{"field": "hal2/02", "class": "build"}, {"field": "hal2/09", "class": "landing"}])
        self.assertEqual(state_run.wait_of(doc, self.FIELD), "waits behind landing 09")
        self.assertEqual(state_run.wait_of(status_doc(waiting=[{"field": "hal2/02"}]), self.FIELD), "waits in the workqueue")

    def test_a_field_is_matched_by_its_folder_never_by_a_prefix_or_another_repository(self):
        doc = status_doc(waiting=[{"field": "jobsearch/02", "class": "build"}, {"field": "hal2/021", "class": "build"}])
        self.assertIsNone(state_run.wait_of(doc, self.FIELD))
        by_cwd = status_doc(waiting=[{"field": "elsewhere", "cwd": self.FIELD + "/code/rust"}])
        self.assertEqual(state_run.wait_of(by_cwd, self.FIELD), "waits in the workqueue")

    def test_a_frozen_run_names_its_hold(self):
        doc = status_doc(frozen=[{"field": "hal2/02", "hold": "a"}], holds=[{"id": "a", "class": "landing", "field": "hal2/16"}])
        self.assertEqual(state_run.wait_of(doc, self.FIELD), "frozen by landing 16")

    def test_an_unknown_document_is_no_wait(self):
        self.assertIsNone(state_run.wait_of(None, self.FIELD))
        self.assertIsNone(state_run.wait_of(status_doc(), self.FIELD))

    def test_a_hold_waiting_for_an_older_hold(self):
        doc = status_doc(holds=[{"id": "a", "class": "landing", "field": "hal2/16", "state": "holding"},
                                {"id": "b", "class": "smuggle", "field": "hal2/02", "state": "waiting"}])
        self.assertEqual(state_run.wait_of(doc, self.FIELD), "waits behind landing 16")


if __name__ == "__main__":
    unittest.main()
