"""Plan 0369 step 1: the statusline's numbers per worktree, the done percentage, the queue in order, the mode's `since`."""

import unittest
from unittest import mock

import state
import state_sources as src
import test_state

REAL_NUMBERS = test_state.REAL["git_numbers"]
STATUS = {"branch": "07", "ahead": 29, "behind": 2, "modified": 3, "deleted": 1, "staged": 4, "upstream": True, "stash": 5,
          "base": "main", "base_ahead": 6, "base_behind": 7}
ZERO = {k: 0 for k in ("behind", "ahead", "stash", "untracked", "added", "modified", "deleted")}


class Numbers(unittest.TestCase):
    def numbers(self, raw):
        with mock.patch.object(src, "tool_json", lambda args, cwd=None: raw):
            return REAL_NUMBERS("/x")

    def test_the_statuslines_mapping(self):
        self.assertEqual(self.numbers(STATUS), {"behind": 7, "ahead": 6, "stash": 5, "untracked": 0, "added": 0, "modified": 7, "deleted": 1})

    def test_missing_counts_are_zero_and_a_failed_tool_is_unknown(self):
        self.assertEqual(self.numbers({"branch": "07"}), ZERO)
        self.assertIsNone(self.numbers(None))
        self.assertIsNone(self.numbers(["not", "an", "object"]))

    def test_the_call_is_one_status_of_the_path(self):
        calls = []
        with mock.patch.object(src, "tool_json", lambda args, cwd=None: calls.append(args) or STATUS):
            REAL_NUMBERS("/some/wt")
        self.assertEqual(calls, [["hal2-cli-git", "status", "--json", "--repo", "/some/wt"]])


class DonePct(unittest.TestCase):
    def test_rounds_half_up_and_is_none_without_steps(self):
        got = [state.done_pct(d, t) for d, t in ((0, 4), (1, 3), (2, 3), (4, 4), (1, 8), (1, 200))]
        self.assertEqual(got, [0, 33, 67, 100, 13, 1])
        self.assertIsNone(state.done_pct(None, None))
        self.assertIsNone(state.done_pct(0, 0))


class InRows(test_state.Fixture):
    def test_rows_carry_git_and_done_pct(self):
        nums = {"behind": 1, "ahead": 2, "stash": 0, "untracked": 0, "added": 0, "modified": 3, "deleted": 0}
        self.mock(src, "git_numbers", lambda path: nums if path.endswith("/02") else None)
        rows = self.rows()
        self.assertEqual(rows["02"]["git"], nums)
        self.assertIsNone(rows["10"]["git"])
        self.assertEqual(rows["02"]["done_pct"], 33)  # one of three steps
        self.assertIsNone(rows["10"]["done_pct"])  # a shot, no steps

    def test_collect_lists_the_queue_in_order(self):
        self.set_tools(queue=[{"slot": "10", "wt": "10", "worktree": None, "position": 0, "holding": True, "state": "held"}])
        self.assertEqual(state.collect(str(self.main))["queue"][0]["wt"], "10")


class QueueOrder(unittest.TestCase):
    def state_of(self, queue, mode=None):
        with mock.patch.object(src, "tool_json", lambda args, cwd=None: {"queue": queue, "mode": mode}):
            return src.queue_state("/m")

    def test_holder_first_then_by_position_with_the_worktree_name(self):
        def t(slot, pos, hold=False, wt=None):
            return {"slot": slot, "worktree": wt, "position": pos, "holding": hold, "state": "waiting"}
        got = self.state_of([t("16", 1), t("20", 3), t("09", 2, True), t(None, 0, wt="/w/hal2/12")])
        self.assertEqual([x["wt"] for x in got["queue"]], ["09", "12", "16", "20"])
        self.assertTrue(got["queue"][0]["holding"])

    def test_mode_gains_since(self):
        mode = {"mode": "smuggle", "by": "user", "at": "2026-10-18T02:09:27Z", "why": "x"}
        got = self.state_of([], mode)["mode"]
        self.assertEqual((got["mode"], got["by"], got["since"], got["at"]), ("smuggle", "user", "2026-10-18T02:09:27Z", "2026-10-18T02:09:27Z"))
        self.assertIsNone(self.state_of([], None)["mode"])


if __name__ == "__main__":
    unittest.main()
