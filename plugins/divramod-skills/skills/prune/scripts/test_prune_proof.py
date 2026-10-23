"""The proof (prune_proof.py, copied from the tollman by plan 0377 step 3, D11): which fields are free and why not. The
tollman's plan and disk report stay with the tollman's tests. No real session, removal or hal2-cli-agents."""

import subprocess
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import prune_proof
import tick
import worktree_farm
from test_farmer import NOW, git
from worktree_farm import NOW_MS


class Scanning:
    def why(self, ctx=None, agents=(), build=lambda path: False):
        found = prune_proof.scan(str(self.main), ctx or {}, None if agents is None else list(agents), NOW_MS, build)
        return {w["slot"]: w["why"] for w in found}


class Slots(Scanning, worktree_farm.Slots):
    pass


class MarkedSlots(Scanning, worktree_farm.MarkedSlots):
    pass


class Scan(Slots):
    def test_only_numbered_slots_and_each_kind_of_unsaved_work(self):
        why = self.why()
        self.assertEqual(sorted(why), ["03", "04", "05", "06", "07", "13", "14"])
        self.assertEqual([s for s, w in why.items() if w is None], ["03", "13", "14"])
        self.assertIn("uncommitted", why["04"])
        self.assertIn("CURRENT_PLAN names 0001-x", why["05"])
        self.assertIn("1 commit(s) not on origin/main", why["06"])
        self.assertIn("side branch 07-ui", why["07"])

    def test_the_heads_are_the_worktree_list_s_and_the_base_is_asked_once_per_scan(self):
        git(self.main, "worktree", "add", "-q", "--orphan", "-b", "15", str(self.base / "15"))  # an unborn branch
        heads = {w["slot"]: w["head"] for w in prune_proof.slots(str(self.main))}
        for slot, head in heads.items():
            asked = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.base / slot, capture_output=True, text=True)
            self.assertEqual(head, asked.stdout.strip() if asked.returncode == 0 else "", slot)
        self.assertEqual(heads["15"], "")
        with mock.patch.object(tick, "default_ref", wraps=tick.default_ref) as ref:
            self.assertIn("1 commit(s) not on origin/main", self.why()["06"])
        self.assertEqual(ref.call_count, 1)

    def test_a_ticket_a_pause_an_open_ask_a_busy_agent_a_build(self):
        self.assertIn("ticket", self.why({"waiting": {"13"}})["13"])
        self.assertIn("ticket", self.why({"landing": {"13"}})["13"])
        ask = [{"at": NOW.isoformat(), "kind": "ask", "slot": "13"}]
        self.assertIn("answer", self.why({"log": ask})["13"])
        busy = {"pane_id": "%9", "checkout": str(self.base / "03"), "state": "blocked", "since": 0}
        self.assertIn("blocked", self.why(agents=[busy])["03"])
        self.assertIn("build", self.why(build=lambda path: path.endswith("13"))["13"])

    def test_a_recent_session_keeps_a_10_99_slot_not_a_00_09_one(self):
        recent = lambda slot: {"pane_id": "%9", "checkout": str(self.base / slot), "state": "idle",  # noqa: E731
                               "since": NOW_MS - 60_000}
        self.assertIn("active", self.why(agents=[recent("13")])["13"])
        self.assertIsNone(self.why(agents=[recent("03")])["03"])
        old = {**recent("13"), "since": NOW_MS - 2 * 3600_000}
        self.assertIsNone(self.why(agents=[old])["13"])

    def test_a_terminal_host_session_in_any_state_but_ended_holds_a_10_99_slot(self):
        """Learning L49 (plan 0412): `t:` panes of a terminal host count; sleeping, idle and failed are live."""
        host = lambda state: {"pane_id": "t:abc", "session": "terminal", "kind": "claude", "state": state,  # noqa: E731
                              "checkout": str(self.base / "13"), "since": NOW_MS - 60_000}
        for state in ("sleeping", "idle", "failed", "done"):
            self.assertIn("active", self.why(agents=[host(state)])["13"], state)
        self.assertIsNone(self.why(agents=[host("ended")])["13"])
        busy = host("working")
        self.assertIn("working", self.why(agents=[busy])["13"])
        old = {**host("failed"), "since": NOW_MS - 2 * 3600_000}
        self.assertEqual([a["pane_id"] for a in prune_proof.sessions([old], str(self.base / "13"))], ["t:abc"])

    def test_the_checkout_matches_by_its_realpath(self):
        link = self.base / "link13"
        link.symlink_to(self.base / "13")
        a = {"pane_id": "t:abc", "checkout": str(link), "state": "idle", "since": NOW_MS - 60_000}
        self.assertIn("active", self.why(agents=[a])["13"])

    def test_an_unreadable_list_refuses_every_slot(self):
        why = self.why(agents=None)
        self.assertTrue(all(w and "could not be read" in w for w in why.values()), why)


class Marked(MarkedSlots):
    def test_a_marked_30_99_slot_is_free_once_its_work_is_in_the_leads_branch(self):
        why = self.why()
        self.assertIsNone(why["31"])
        self.assertIsNone(why["33"])
        self.assertIn("HEAD: 1 commit(s) not in origin/02", why["32"])

    def test_a_branch_or_side_branch_the_lead_lacks_or_a_change_keeps_it(self):
        git(self.base / "31", "branch", "31-x")
        git(self.base / "31", "switch", "-q", "31-x")
        git(self.base / "31", "commit", "-q", "--allow-empty", "-m", "side")
        git(self.base / "31", "switch", "-q", "31")
        self.assertIn("31-x: 1 commit(s) not in origin/02", self.why()["31"])
        (self.base / "33/new.txt").write_text("x")
        self.assertIn("uncommitted", self.why()["33"])
        git(self.base / "32", "reset", "-q", "--hard", "origin/02")  # HEAD in origin/02, origin/32 not
        self.assertIn("origin/32: 1 commit(s) not in origin/02", self.why()["32"])

    def test_a_session_active_or_a_lead_written_in_the_last_hour_keeps_it(self):
        self.assertIn("active in the last 60 min", self.why(agents=[self.agent("31", 40)])["31"])
        self.assertIsNone(self.why(agents=[self.agent("31", 61)])["31"])
        self.assertIsNone(self.why(agents=[self.agent("13", 40)])["13"], "unmarked 10-99: 30 min, unchanged")
        busy = {**self.agent("31", 120), "state": "working"}
        self.assertIn("working", self.why(agents=[busy])["31"])
        self.mark("31", age=10 * 60)  # the foreman's `assign` reused it
        self.assertIn("plans/LEAD was written in the last 60 min", self.why()["31"])
        self.assertIn("ticket", self.why({"waiting": {"33"}})["33"])
        self.assertIn("build", self.why(build=lambda path: path.endswith("33"))["33"])

    def test_a_marked_slot_below_30_or_a_bad_marker_or_a_missing_lead_branch_is_never_pruned(self):
        why = self.why()
        self.assertIn("below 30", why["12"])
        self.mark("33", lead="99")
        self.assertIn("origin/99 does not exist", self.why()["33"])
        (self.base / "33/plans/LEAD").write_text("nonsense\n")
        self.assertIn("plans/LEAD is not", self.why()["33"])

    def test_unmarked_slots_are_unchanged(self):
        why = self.why()
        self.assertEqual([s for s in ("03", "13", "14") if why[s] is None], ["03", "13", "14"])
        self.assertIn("1 commit(s) not on origin/main", why["06"])
        self.assertIn("7 commit(s) not on origin/main", why["02"], "the lead's own slot, unmarked")


if __name__ == "__main__":
    unittest.main()
