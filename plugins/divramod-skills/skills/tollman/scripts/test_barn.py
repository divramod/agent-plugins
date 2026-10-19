"""After the barn (hal2 plan 0360 step 7, D8; barn.py; on /prune's facts since plan 0377 step 7, D12): the cars of the last
landed train on the rounds after it. A field 00-09 that is free and mucked out has its session cleared once
(hal2-cli-agents is a fake), one that still holds work is woken for once after 24 hours, never removed by force; a car
10-99 is removed by /prune's run, its plan names the cars first (a fake /prune plan here). No real session, clear or
removal."""

import datetime as dt
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import barn
import prune
import tick
import trains
from test_prune import STUB, data, todo

NOW = dt.datetime(2026, 10, 18, 10, 0, tzinfo=dt.timezone.utc)
LANDED = {"kind": "landed", "slot": "tollman-hal2", "at": "2026-10-18T10:00:00Z", "train": "03+04+14@x",
          "cars": ["03", "04", "14"], "run": "https://x/runs/9"}


class AfterTheBarn(unittest.TestCase):
    """03 (free, a session), 04 (an uncommitted file, a session), 13 and 14 (free): the train of 03, 04, 14 landed at NOW."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.main = str(self.tmp / "hal2")
        Path(self.main).mkdir()
        self.fields = []
        for slot in ("03", "04", "13", "14"):
            (self.tmp / slot).mkdir()
            self.fields.append({"slot": slot, "path": str(self.tmp / slot), "head": f"h{slot}", "size": None,
                                "proof": "uncommitted changes" if slot == "04" else None,
                                "sessions": [{"pane_id": f"%{slot}", "state": "idle", "since": 0}] if slot in ("03", "04") else []})
        self.stub = self.tmp / "stub" / "prune.py"
        self.stub.parent.mkdir()
        self.stub.write_text(STUB)
        (self.tmp / "state").mkdir()
        for patch in (mock.patch.object(prune, "script", return_value=self.stub),
                      mock.patch.object(prune, "state", return_value=self.tmp / "state"),
                      mock.patch.object(tick.mtm_scan, "DATA", self.tmp / "roles"),
                      mock.patch.object(barn.train_state, "lines", side_effect=lambda main: [LANDED])):
            patch.start()
            self.addCleanup(patch.stop)

    def round(self, log=(), hours=1.0, prune_plan=None):
        """A round `hours` after the landing: the prune duty's fresh actions, on a canned /prune plan (the cars first)."""
        now = NOW + dt.timedelta(hours=hours)
        plan = prune_plan or [todo("03", "muck-out"), todo("14", "remove"), todo("13", "remove")]
        (self.stub.parent / "plan.json").write_text(json.dumps(data(self.fields, **{"phase-1": {"actions": plan}})))
        ctx = {"main": self.main, "top": "/x/tollman-hal2", "now": now, "log": list(log)}
        return tick.fresh(prune.plan({}, ctx), list(log), now)

    def done(self, actions, log=()):
        """The actions carried out by the tick (hal2-cli-agents and the start are fakes), and the log after them."""
        calls, out = [], {}
        with mock.patch.object(tick, "sh", side_effect=lambda argv, cwd, timeout=900: calls.append(argv) or (0, "")):
            for a in actions:
                tick.execute(dict(a), "/x/tollman-hal2", self.main, out)
        at = NOW.isoformat()
        return calls, list(log) + [{"at": at, "key": a["key"], "note": ""} for a in actions if a.get("key")], out

    def kinds(self, actions):
        return [(a["kind"], a["slot"]) for a in actions if a["kind"] not in ("disk", "low-disk")]

    def test_the_last_landed_train_s_cars(self):
        self.assertEqual(barn.cars(barn.last_landed(self.main)), ["03", "04", "14"])
        self.assertEqual(barn.cars({"cars": ["yard", "03"]}), ["03"], "the yard has no field")

    def test_a_clean_00_09_car_is_cleared_once_after_it_was_mucked_out(self):
        first = self.round()
        self.assertEqual(self.kinds(first), [("clean", "03"), ("remove", "14")], "no clear before the muck out; one removal")
        _, log, _ = self.done([a for a in first if a["kind"] == "clean"])
        clear = [a for a in self.round(log) if a["kind"] == "barn-clear"]
        self.assertEqual([a["slot"] for a in clear], ["03"])
        self.assertEqual(clear[0]["key"], "barn-clear:03:h03")
        calls, log, _ = self.done(clear, log)
        self.assertEqual(calls, [["hal2-cli-agents", "clear-and-continue", "--pane", "%03", "--without-plan",
                                  "--prompt", "/merge-from-main", "--detach"]])
        self.assertEqual([a for a in self.round(log) if a["kind"] == "barn-clear"], [], "once")

    def test_a_failed_muck_out_or_no_session_clears_nothing(self):
        clean = next(a for a in self.round() if a["kind"] == "clean")
        failed = [{"at": NOW.isoformat(), "key": clean["key"], "note": " (exit 1)"}]
        self.assertNotIn("barn-clear", [a["kind"] for a in self.round(failed)])
        self.fields[0]["sessions"] = []
        ok = [{"at": NOW.isoformat(), "key": clean["key"], "note": ""}]
        self.assertNotIn("barn-clear", [a["kind"] for a in self.round(ok)])

    def test_a_dirty_car_is_not_cleared_and_wakes_once_after_24_hours(self):
        self.assertEqual([a for a in self.round(hours=23) if a["slot"] == "04"], [])
        late = [a for a in self.round(hours=25) if a["slot"] == "04"]
        self.assertEqual([(a["kind"], a["do"]) for a in late], [("barn-stuck", "wake")])
        self.assertEqual(late[0]["key"], "barn-stuck:04:h04")
        self.assertIn("uncommitted", late[0]["text"])
        _, log, out = self.done(late)
        self.assertEqual([a["kind"] for a in out["wake"]], ["barn-stuck"])
        self.assertEqual([a for a in self.round(log, hours=26) if a["slot"] == "04"], [], "once")

    def test_a_car_above_09_is_started_for_removal_before_other_free_fields(self):
        remove = [a for a in self.round() if a["kind"] == "remove"]
        self.assertEqual([a["slot"] for a in remove], ["14"], "13 is free too, but /prune names the car 14 first")
        run = self.round()[0]  # the round's one run action carries every field it started
        self.assertEqual(run["argv"][2], "start", "a detached /prune run, never a removal under the tick's timeout")
        self.assertEqual(run["argv"][-4:], ["--field", "03", "--field", "14"])

    def test_the_barn_text_leaves_the_clear_to_the_tollman(self):
        text = trains.TEXT["barn"].format(cars="03, 14", run=", https://x/runs/9")
        self.assertIn("your crop is in the barn (the train of 03, 14, https://x/runs/9): /merge-from-main, finish the plan, "
                      "once finished /cleanup, then clear (the tollman clears a field 00-09 and removes a field "
                      "above 09 once its work is safe)", text)

    def test_no_landed_train_no_barn_actions(self):
        self.assertEqual(barn.actions({"main": self.main, "now": NOW}, [], None), [])


if __name__ == "__main__":
    unittest.main()
