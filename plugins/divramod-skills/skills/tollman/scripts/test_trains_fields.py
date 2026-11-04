"""Hal2 plan 0383 step 16 (D16): a foreman works in any field 00-99, so its wagon from field 30 rides a train; only a
field holding `plans/LEAD` (a servant's, whatever its number) never hitches. Plan 0610 step 1 (`Rides`): every hitched
wagon rides, or waits under a user-named exception (trains_draft.EXCEPTIONS). Real git (test_trains.Crops)."""
# enforces .adr/tollman.md

import datetime as dt
import unittest
from pathlib import Path
from unittest import mock

import test_trains as tt
import trains
import trains_draft
import trial


class Fields(tt.Crops):
    def test_a_foremans_wagon_from_field_30_and_from_field_99_rides(self):
        q = self.queue(**{"07": {"seven.rs": "7\n"}, "30": {"thirty.rs": "30\n"}, "99": {"ninety.rs": "99\n"}})
        d = self.draft(q)
        self.assertEqual((self.cars(d), d["unhitched"]), (["07", "30", "99"], []))

    def test_a_field_holding_plans_lead_never_rides_whatever_its_number(self):
        q = self.queue(**{"07": {"seven.rs": "7\n"}, "05": {"five.rs": "5\n"}, "30": {"thirty.rs": "30\n"}})
        q[1]["worktree"] = self.servant_field()
        d = self.draft(q)
        self.assertEqual(self.cars(d), ["07", "30"])
        self.assertEqual((d["unhitched"], [w["field"] for w in d["waiting"]]), ([], ["05"]), "it waits, hitched")

    def test_servant_reads_the_marker_not_the_number(self):
        self.assertTrue(trains.servant(self.servant_field()))
        self.assertFalse(trains.servant(self.d) or trains.servant(None) or trains.servant(""))



class Rides(tt.Crops):
    def test_a_gone_worktree_rides_from_its_hitched_sha_and_the_farmer_gets_a_note(self):
        # Plan 0610 E13: its worktree was removed; before, it was unhitched and nobody was told.
        (q,) = self.queue(**{"05": {"gone.rs": "g\n"}})
        q["worktree"] = str(Path(self.d) / "no-such-field")
        d = self.draft([q])
        self.assertEqual(d["cars"], [{"field": "05", "branch": "05", "head": q["ready"]["head"], "plan": "",
                                      "gone": True}])
        note, form = trains.train_actions("/f/tollman-hal2", d, {})
        self.assertEqual((note["kind"], note["do"], note["slot"], form["kind"]),
                         ("worktree-gone", "record", "tollman-hal2", "form"))
        self.assertIn("05's worktree is gone", note["text"])

    def test_a_ticket_in_its_own_landing_is_listed(self):
        (q,) = self.queue(**{"07": {"seven.rs": "7\n"}})
        d = self.draft([dict(q, state="active")])
        self.assertEqual((d["cars"], d["waiting"]),
                         ([], [{"field": "07", "why": "own landing: its ticket is active", "reason": "own-landing"}]))

    def test_a_head_the_carrier_holds_already_is_a_car_never_proven_again(self):
        # Plan 0610 E9 (field 79, 2026-11-04 11:48Z): the six hand-merged heads were proven again and shown held.
        q = self.queue(**{"15": {"fifteen.rs": "15\n"}, "44": {"forty.rs": "44\n"}})
        carrier = trial.merge(self.d, "main", q[0]["ready"]["head"])[0]
        asked = []
        with mock.patch.object(trains, "PROVE", lambda m, w, h, b: asked.append(h) or {"state": "green", "lines": []}):
            d = trains.draft(self.d, q, "tollman-hal2", "main", "main", carried=[carrier])
            on = trains.draft(self.d, q, "tollman-hal2", carrier, "main")
        self.assertEqual([(c["field"], c.get("carried")) for c in d["cars"]], [("15", True), ("44", None)])
        self.assertEqual([(c["field"], c.get("carried")) for c in on["cars"]], [("15", True), ("44", None)])
        self.assertEqual(asked, [q[1]["ready"]["head"]] * 2, "only 44 is proven")

    def test_a_trial_that_cannot_run_is_tried_again_then_the_car_rides_untried(self):
        # Plan 0610 E15: before, it waited and a train formed without it.
        q = self.queue(**{"07": {"seven.rs": "7\n"}, "09": {"nine.rs": "9\n"}})
        real, calls = trial.merge, []

        def merge(repo, ours, theirs):
            calls.append(theirs)
            return (None, []) if theirs == q[0]["ready"]["head"] else real(repo, ours, theirs)
        with mock.patch.object(trial, "merge", merge):
            d = self.draft(q)
        self.assertEqual(self.cars(d), ["07", "09"])
        self.assertIn("could not run", d["cars"][0]["untried"])
        self.assertEqual(calls.count(q[0]["ready"]["head"]), 2, "tried once more")

    def test_a_proof_that_waits_rides_with_proof_unknown(self):
        # Plan 0610 E16: the records checker too old, a scratch locked: the pretest and the gate run the checks.
        (q,) = self.queue(**{"07": {"docs/x.md": "x\n"}})
        with mock.patch.object(trains, "PROVE", lambda *a: {"state": "wait", "lines": ["no proof yet: locked"]}):
            d = self.draft([q])
        self.assertEqual((self.cars(d), d["cars"][0]["proof_unknown"], d["waiting"]),
                         (["07"], ["no proof yet: locked"], []))

    def test_the_barn_s_own_red_is_the_barn_s_fix_order_first(self):
        # Field 79 row 13 (plan 0610 D18): the alt-shift-x clash the barn held showed on all six cars.
        (q,) = self.queue(**{"07": {"seven.rs": "7\n"}})
        line = "keys: a.json: key alt-shift-x (everywhere): held by app a and app b"
        with mock.patch.object(trains, "PROVE", lambda *a: {"state": "green", "lines": [], "barn_red": [line]}):
            d = self.draft([q])
        self.assertEqual((self.cars(d), d["barn_red"]), (["07"], [{"field": "07", "lines": [line]}]))
        self.assertNotIn("proof_red", d["cars"][0], "never the car's")
        (order,) = trains.train_actions("/f", d, {})
        self.assertEqual((order["kind"], order["argv"][1:4]), ("barn-red", [str(trains.TOLLMAN), "order", "main"]))
        self.assertIn("alt-shift-x", order["argv"][5])
        self.assertEqual([a["kind"] for a in trains.train_actions("/f", d, {}, barn_fix=True)], ["form"],
                         "the barn's fix waits to ride: the train forms on it")
        ran = [{"key": order["key"], "at": tt.AT, "exit": 1}]  # D12: the order ran (done or failed): never a block
        self.assertEqual([a["kind"] for a in trains.train_actions("/f", d, {}, log=ran)], ["barn-red", "form"])

    def test_an_open_barn_fix_holds_forming_only_while_young(self):
        # Plan 0610 D12 (E22): the barn's own open fix order holds the next train 30 minutes, then it forms beside it.
        (q,) = self.queue(**{"07": {"seven.rs": "7\n"}})
        order = {"schema": 1, "at": tt.AT, "kind": "order", "slot": "tollman-hal2", "field": "main", "id": "main-1",
                 "branch": "tollman-train-fix", "base": "b" * 40, "why": "red"}
        at = trains.roletime.parse(tt.AT)
        with mock.patch.object(trains, "default_ref", lambda repo: "main"):
            def plan(minutes):
                return trains.plan("/no/such/farm/tollman-hal2", self.d, [q], [order], {}, alive=lambda p: False,
                                   result=lambda m: None, now=at + dt.timedelta(minutes=minutes))
            self.assertEqual(plan(10), [], "young: the train waits for its first car")
            self.assertEqual([a["kind"] for a in plan(40) if a["do"] == "run"], ["form"], "old: it forms beside it")

    def test_a_smuggle_entry_and_the_wagons_it_cuts_off_wait_under_their_own_reasons(self):
        q = self.queue(**{"07": {"seven.rs": "7\n"}, "08": {"eight.rs": "8\n"}, "09": {"nine.rs": "9\n"}})
        q[1]["effective_mode"] = "smuggle"
        d = self.draft(q)
        self.assertEqual((self.cars(d), [(w["field"], w["reason"]) for w in d["waiting"]]),
                         (["07"], [("08", "smuggle"), ("09", "smuggler-ahead")]), "the closing pass moves neither")

    def test_every_way_in_marks_a_gone_worktree_and_a_ticket_without_one_is_proven_from_the_barn_s_checkout(self):
        q = self.queue(**{"15": {"fifteen.rs": "15\n"}, "16": {"sixteen.rs": "16\n"}, "17": {"s.rs": "17\n"}})
        q[0]["worktree"] = str(Path(self.d) / "gone-15")
        del q[2]["worktree"]
        carrier, asked = trial.merge(self.d, "main", q[0]["ready"]["head"])[0], []
        with mock.patch.object(trains, "PROVE", lambda m, w, h, b: asked.append(w) or {"state": "green", "lines": []}):
            d = trains.draft(self.d, q, "tollman-hal2", "main", "main", carried=[carrier])
        self.assertEqual([(c["field"], c.get("carried"), c.get("gone")) for c in d["cars"]],
                         [("15", True, True), ("16", None, None), ("17", None, True)])
        self.assertEqual((Path(asked[1]).name, Path(asked[1]).is_dir()), ("17", False), "never \"\": a wait")
        moved = trains_draft.close(q[:1], "tollman-hal2", {"cars": [], "waiting": [], "unhitched": [], "alone": False})
        self.assertEqual(moved["cars"][0].get("gone"), True, "moved in: the board note follows too")
        self.assertEqual([a["kind"] for a in trains.train_actions("/f/t", d, {})], ["worktree-gone"] * 2 + ["form"])

    def test_every_ready_ticket_ends_a_car_or_under_a_user_named_exception(self):
        # Plan 0610 D20: plan 0595's train_depends.py ("waits for its dependency", 2942270660) cannot bring a hold back.
        self.assertEqual(set(trains.EXCEPTIONS), {"servant", "barn", "smuggle", "smuggler-ahead", "asleep", "reserved",
                                                  "hold", "own-landing", "alone", "minimum"})
        q = self.queue(**{"07": {"seven.rs": "7\n"}, "09": {"nine.rs": "9\n"}, "14": {"f.rs": "14\n"}})
        out = {"base": "main", "cars": [trains_draft.car(q[0]), trains_draft.car(q[1])], "unhitched": [],
               "alone": False, "barn_red": [],
               "waiting": [{"field": "14", "why": "waits for its dependency 0590", "after": "07"}]}
        d = trains_draft.close(q, "tollman-hal2", out)
        self.assertEqual((self.cars(d), d["waiting"]), (["07", "14", "09"], []), "after its dependency")
        self.assertEqual(d["cars"][1]["moved_in"], "waits for its dependency 0590")
        out = {"base": "main", "cars": [trains_draft.car(q[0])], "unhitched": [], "alone": False, "barn_red": [],
               "waiting": [{"field": "14", "why": "some new reason"}]}
        self.assertEqual(self.cars(trains_draft.close(q, "tollman-hal2", out)), ["07", "09", "14"],
                         "an unknown reason and a ticket in no list both ride")
        out = {"base": "main", "cars": [trains_draft.car(q[0])], "unhitched": [], "alone": False, "barn_red": [],
               "waiting": [{"field": "09", "why": "waits for 14", "after": "14"}, {"field": "14", "why": "new"}]}
        self.assertEqual(self.cars(trains_draft.close(q, "tollman-hal2", out)), ["07", "14", "09"],
                         "a dependency moved in later goes first")


if __name__ == "__main__":
    unittest.main()
