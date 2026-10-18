"""After the barn (hal2 plan 0360 step 7, D8; barn.py): the cars of the last landed train on the rounds after it. A
field 00-09 that is free and mucked out has its session cleared once (hal2-cli-agents is a fake), one that still
holds work is woken for once after 24 hours, never removed by force; a car 10-99 is removed before other free
fields. No real session, clear or removal."""

import datetime as dt
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import barn
import prune
import prune_proof
import tick
import train_state
import trains
import worktree_farm
from test_farmer import NOW
from worktree_farm import NOW_MS

INFO = {"free_gb": 400.0, "biggest": []}
CARRIER = "tollman-hal2"


class AfterTheBarn(worktree_farm.Slots):
    """03 (free), 04 (an uncommitted file), 13 and 14 (free): the train of 03, 04 and 14 landed at NOW."""

    def setUp(self):
        super().setUp()
        train_state.append(str(self.main), "landed", CARRIER, NOW, train="03+04+14@x", cars=["03", "04", "14"],
                           run="https://x/runs/9")
        self.agents = {f"%{s}": {"pane_id": f"%{s}", "checkout": str(self.base / s), "state": "idle", "since": 0}
                       for s in ("03", "04")}

    def head(self, slot):
        return tick.git(str(self.base / slot), "rev-parse", "HEAD")

    def round(self, log=(), hours=1.0):
        """A round `hours` after the landing: the prune duty's fresh actions, with the frame's context."""
        now = NOW + dt.timedelta(hours=hours)
        found = prune_proof.scan(str(self.main), {}, list(self.agents.values()), NOW_MS, lambda path: False)
        ctx = {"main": str(self.main), "now": now, "log": list(log), "agents_by_pane": self.agents}
        return tick.fresh(prune.plan({}, ctx, found, INFO), list(log), now)

    def done(self, actions, log=()):
        """The actions carried out by the tick (hal2-cli-agents and the removal are fakes), and the log after them."""
        calls, out = [], {}
        with mock.patch.object(tick, "sh", side_effect=lambda argv, cwd, timeout=900: calls.append(argv) or (0, "")):
            for a in actions:
                tick.execute(dict(a), str(self.slot), str(self.main), out)
        at = NOW.isoformat()
        return calls, list(log) + [{"at": at, "key": a["key"], "note": ""} for a in actions if a.get("key")], out

    def kinds(self, actions):
        return [(a["kind"], a["slot"]) for a in actions if a["kind"] != "disk"]

    def test_the_last_landed_train_s_cars(self):
        landed = barn.last_landed(str(self.main))
        self.assertEqual(barn.cars(landed), ["03", "04", "14"])
        self.assertEqual(barn.cars({"cars": ["yard", "03"]}), ["03"], "the yard has no field")

    def test_a_clean_00_09_car_is_cleared_once_after_it_was_mucked_out(self):
        first = self.round()
        self.assertEqual(self.kinds(first), [("clean", "03"), ("remove", "14")], "no clear before the muck out")
        calls, log, _ = self.done([a for a in first if a["kind"] == "clean"])
        second = self.round(log)
        clear = [a for a in second if a["kind"] == "barn-clear"]
        self.assertEqual([a["slot"] for a in clear], ["03"])
        self.assertEqual(clear[0]["key"], f"barn-clear:03:{self.head('03')}")
        calls, log, _ = self.done(clear, log)
        self.assertEqual(calls, [["hal2-cli-agents", "clear-and-continue", "--pane", "%03", "--without-plan",
                                  "--prompt", "/merge-from-main", "--detach"]])
        self.assertEqual([a for a in self.round(log) if a["kind"] == "barn-clear"], [], "once")

    def test_a_failed_muck_out_or_no_session_clears_nothing(self):
        clean = next(a for a in self.round() if a["kind"] == "clean")
        failed = [{"at": NOW.isoformat(), "key": clean["key"], "note": " (exit 1)"}]
        self.assertNotIn("barn-clear", [a["kind"] for a in self.round(failed)])
        del self.agents["%03"]
        ok = [{"at": NOW.isoformat(), "key": clean["key"], "note": ""}]
        self.assertNotIn("barn-clear", [a["kind"] for a in self.round(ok)])

    def test_a_dirty_car_is_not_cleared_and_wakes_once_after_24_hours(self):
        self.assertEqual([a for a in self.round(hours=23) if a["slot"] == "04"], [])
        late = [a for a in self.round(hours=25) if a["slot"] == "04"]
        self.assertEqual([(a["kind"], a["do"]) for a in late], [("barn-stuck", "wake")])
        self.assertEqual(late[0]["key"], f"barn-stuck:04:{self.head('04')}")
        self.assertIn("uncommitted", late[0]["text"])
        _, log, out = self.done(late)
        self.assertEqual([a["kind"] for a in out["wake"]], ["barn-stuck"])
        self.assertEqual([a for a in self.round(log, hours=26) if a["slot"] == "04"], [], "once")

    def test_a_car_above_09_is_removed_before_other_free_fields(self):
        remove = [a for a in self.round() if a["kind"] == "remove"]
        self.assertEqual([a["slot"] for a in remove], ["14"], "13 is free too, but 14 rode the train")
        self.assertEqual(remove[0]["argv"][-4:], ["remove", "14", "--repo", str(self.main)])
        train_state.append(str(self.main), "landed", CARRIER, NOW, train="03@y", cars=["03"])
        self.assertEqual([a["slot"] for a in self.round() if a["kind"] == "remove"], ["13"], "no car: in order")

    def test_the_barn_text_leaves_the_clear_to_the_tollman(self):
        text = trains.TEXT["barn"].format(cars="03, 14", run=", https://x/runs/9")
        self.assertIn("your crop is in the barn (the train of 03, 14, https://x/runs/9): /merge-from-main, finish the plan, "
                      "once finished /cleanup, then clear (the tollman clears a field 00-09 and removes a field "
                      "above 09 once its work is safe)", text)

    def test_no_landed_train_no_barn_actions(self):
        found = prune_proof.scan(str(self.main), {}, [], NOW_MS, lambda path: False)
        self.assertEqual(barn.actions({"main": str(self.main), "now": NOW}, found, None), [])


if __name__ == "__main__":
    unittest.main()
