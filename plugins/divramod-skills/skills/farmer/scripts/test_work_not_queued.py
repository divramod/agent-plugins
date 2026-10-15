"""`work-not-queued` never reads a working session as sleeping (hal2 plan 0313 step 3).

Replays the wagon master's wrong wakes of 2026-10-14 (its roles/wagon-master/log.jsonl, local times): 07 at 10:54
("agent sleeping for 54 min", a shell running), 00 at 11:22 ("sleeping for 38 min", mid-plan, a step's subagent
running) and 02 at 12:14 ("sleeping for 31 min", background waits on its deploy). The sessions are given as
`hal2-cli-agents list --json` entries and go through the scan's own `worktree_entry` into `findings`.
"""

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import mtm_scan as scan

MIN = 60


def agent(slot: str, state: str, quiet_min: int, *tasks: tuple[str, str]) -> dict:
    """A `hal2-cli-agents list --json` entry: `since` in ms, background tasks as (type, description)."""
    return {"project": "/a/hal2", "slot": slot, "kind": "claude", "state": state, "pane_id": f"t:{slot}",
            "since": int((time.time() - quiet_min * MIN) * 1000),
            "background_tasks": [{"id": f"b{i}", "type": t, "description": d} for i, (t, d) in enumerate(tasks)]}


CASES = {  # field: (commits not on main, plan, the session)
    "07": (8, "0301-shada-guard", agent("07", "sleeping", 54, ("shell", "nvim --headless ... PlenaryBustedFile"))),
    "00": (48, "0253-mobile-app", agent("00", "sleeping", 38, ("subagent", "Plan 0253 row 10: ..."))),
    "02": (7, "0267-a-node-in-two-steps", agent("02", "sleeping", 31, ("shell", "Wait for deploy to finish"),
                                                ("shell", "Wait for node demo to finish"))),
    "14": (3, "0300-x", agent("14", "blocked-question", 90)),  # waits on the user: never a queue nag
    "32": (8, "0296-research-mvp-and-money", agent("32", "sleeping", 102, ("cron", "0 3 * * *: /daily"))),
}


class WorkingSessionsAreNotWoken(unittest.TestCase):
    def findings(self) -> list[tuple[str, str]]:
        now = time.time()
        with tempfile.TemporaryDirectory() as d:
            entries = []
            for slot, (ahead, plan, a) in CASES.items():
                (Path(d) / slot / "plans").mkdir(parents=True)
                (Path(d) / slot / "plans/CURRENT_PLAN").write_text(plan + "\n")
                with mock.patch.object(scan, "unmerged", return_value=ahead):
                    entries.append(scan.worktree_entry({"path": str(Path(d) / slot), "branch": slot}, a, "main", now))
        snap = {"now": now, "queue": [], "worktrees": entries, "landings": [], "tests": {},
                "load": {"load1": 4.0, "cores": 10, "per_core": 0.4}, "paused": None}
        return [(f["kind"], f["slot"]) for f in scan.findings(snap)]

    def test_busy_waiting_and_blocked_sessions_get_no_work_not_queued(self):
        got = self.findings()
        for slot in ("07", "00", "02", "14"):
            self.assertNotIn(("work-not-queued", slot), got, f"{slot}'s session works")

    def test_a_truly_sleeping_field_with_unqueued_work_is_still_found(self):
        # 32: research plan done, nothing running but a cron prompt: the same finding as at 09:53, 11:04 and 12:14.
        self.assertEqual(self.findings(), [("work-not-queued", "32")])

    def test_session_works_reads_the_states_and_tasks(self):
        self.assertTrue(scan.session_works({"agent_state": "working"}))
        self.assertTrue(scan.session_works({"agent_state": "blocked-permission"}))
        self.assertTrue(scan.session_works({"agent_state": "idle", "agent_tasks": 2}))
        self.assertFalse(scan.session_works({"agent_state": "sleeping", "agent_tasks": 0}))
        self.assertFalse(scan.session_works({"agent_state": None}))


if __name__ == "__main__":
    unittest.main()
