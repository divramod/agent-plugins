"""The per-field facts of prune's plan (field_facts.py; hal2 plan 0377 step 4): pointers and their plans' states, unsaved
work behind a pointer, a servant's lead, the last train's cars, builds. Fake plan lookups and builds; git on the farmer's
scratch farm for the few tests that need commits."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import facts
import field_facts
import mtm_scan
import plan as planner
import test_facts
from worktree_farm import NOW_MS


def lookup(states):
    """A plan lookup answering from {plan: state} and recording its calls."""
    calls = []

    def fn(plan, repos):
        calls.append((plan, repos))
        return states.get(plan, "missing")
    fn.calls = calls
    return fn


class PlanState(unittest.TestCase):
    def run_with(self, *answers):
        it = iter(answers)
        return field_facts.plan_state("0149-x", ["/field", "/main"], lambda plan, repo: next(it))

    def test_done_or_a_finish_date_is_finished_anything_else_open(self):
        self.assertEqual(self.run_with((0, json.dumps({"state": "done"}), "")), "finished")
        self.assertEqual(self.run_with((0, json.dumps({"state": "active", "finished": "2026-10-01"}), "")), "finished")
        self.assertEqual(self.run_with((0, json.dumps({"state": "active", "finished": None}), "")), "open")

    def test_missing_only_when_every_checkout_does_not_know_it(self):
        none = (1, "", 'hal2-cli-plans: no plan matches "0149-x"')
        self.assertEqual(self.run_with(none, none), "missing")
        self.assertEqual(self.run_with(none, (0, json.dumps({"state": "active"}), "")), "open")

    def test_what_it_does_not_understand_is_unknown_never_stale(self):
        none = (1, "", 'hal2-cli-plans: no plan matches "0149-x"')
        for answers in (((0, "not json", ""),), ((0, "[]", ""),), ((1, "", "boom"),), ((-1, "", "not installed"),),
                        (none, (1, "", "boom"))):
            self.assertEqual(self.run_with(*answers), "unknown", answers)


class Pointers(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def write(self, text):
        (self.dir / "plans").mkdir(exist_ok=True)
        (self.dir / "plans/CURRENT_PLAN").write_text(text)

    def test_the_first_line_of_current_plan(self):
        self.assertIsNone(field_facts.pointer_name(str(self.dir)))
        self.write("\n")
        self.assertIsNone(field_facts.pointer_name(str(self.dir)))
        self.write("0149-x\nsecond\n")
        self.assertEqual(field_facts.pointer_name(str(self.dir)), "0149-x")

    def test_pointer_asks_the_field_then_the_main_checkout(self):
        self.write("0149-x\n")
        fn = lookup({"0149-x": "finished"})
        got = field_facts.pointer({"path": str(self.dir)}, "/main", fn)
        self.assertEqual(got, {"plan": "0149-x", "state": "finished"})
        self.assertEqual(fn.calls, [("0149-x", [str(self.dir), "/main"])])

    def test_a_field_without_a_pointer_asks_nothing(self):
        fn = lookup({})
        self.assertIsNone(field_facts.pointer({"path": str(self.dir)}, "/main", fn))
        self.assertEqual(fn.calls, [])

    def test_a_servants_pointer_is_its_foremans_plan_and_not_looked_at(self):
        self.write("0013-parallel\n")
        (self.dir / "plans/LEAD").write_text("02 0013-parallel 4\n")
        fn = lookup({})
        self.assertIsNone(field_facts.pointer({"path": str(self.dir)}, "/main", fn))
        self.assertEqual(fn.calls, [])


class Cars(unittest.TestCase):
    def test_the_newest_landed_trains_cars_only_real_fields(self):
        main = Path(tempfile.mkdtemp()) / "hal2"
        main.mkdir()
        data = Path(tempfile.mkdtemp())
        with mock.patch.object(mtm_scan, "DATA", data):
            self.assertEqual(field_facts.last_cars(str(main)), [])
            folder = mtm_scan.state_dir(str(main), "tollman")
            rows = [{"kind": "landed", "cars": ["03", "04"]}, {"kind": "formed", "cars": ["09"]},
                    {"kind": "landed", "cars": ["13", "yard", "x"]}, {"kind": "red", "cars": ["14"]}]
            (folder / "train.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n{torn\n")
            self.assertEqual(field_facts.last_cars(str(main)), ["13"])


class Building(unittest.TestCase):
    def test_every_field_asked_in_parallel_and_none_asked_when_there_are_none(self):
        fs = [{"slot": "13", "path": "/w/13"}, {"slot": "14", "path": "/w/14"}]
        self.assertEqual(field_facts.building(fs, lambda path: path.endswith("14")), {"13": False, "14": True})
        self.assertEqual(field_facts.building([], lambda path: self.fail()), {})


class OnFarm(test_facts.Farm):
    def field(self, slot):
        return next(f for f in facts.fields(str(self.main)) if f["slot"] == slot)

    def test_unsaved_work_without_the_pointer_line(self):
        self.assertEqual(field_facts.unsaved(self.field("05")), [])  # only a CURRENT_PLAN
        self.assertEqual(field_facts.unsaved(self.field("04")), ["uncommitted changes"])
        self.assertIn("1 commit(s) not on", field_facts.unsaved(self.field("06"))[0])
        self.assertEqual(field_facts.unsaved(self.field("03")), [])

    def test_a_servants_lead_what_its_foremans_branch_lacks(self):
        self.assertEqual(field_facts.lead(self.field("03")), None)
        ok = field_facts.lead(self.field("31"))
        self.assertEqual((ok["slot"], ok["missing"]), ("02", []))
        self.assertGreater(ok["at"], 0)
        miss = field_facts.lead(self.field("32"))
        self.assertIn("commit(s) not in origin/02", miss["missing"][0])
        (self.base / "33/plans/LEAD").write_text("not a marker\n")
        self.assertIn("bad", field_facts.lead(self.field("33")))
        (self.base / "33/plans/LEAD").write_text("77 0013-x 1\n")
        self.assertIn("does not exist", field_facts.lead(self.field("33"))["bad"])

    def test_extra_gathers_the_facts_and_asks_for_builds_only_where_the_proof_said_no(self):
        fs = [self.field(s) for s in ("03", "05", "06", "31")]
        ctx = {"waiting": {"06"}, "landing": set(), "log": [], "farmer_log": []}
        asked = []
        free = {"03": True, "05": False, "06": False, "31": True}
        more = field_facts.extra(fs, ctx, str(self.main), free, lookup({"0001-x": "finished"}),
                                 lambda path: asked.append(path) or path.endswith("06"))
        self.assertEqual(sorted(Path(p).name for p in asked), ["05", "06"])
        self.assertEqual(more["05"]["pointer"], {"plan": "0001-x", "state": "finished"})
        self.assertEqual(more["05"]["unsaved"], [])
        self.assertIsNone(more["03"]["pointer"])
        self.assertIsNone(more["03"]["unsaved"])
        self.assertIn("ticket", more["06"]["hold"])
        self.assertTrue(more["06"]["building"] and not more["05"]["building"] and not more["03"]["building"])
        self.assertEqual(more["31"]["lead"]["slot"], "02")
        self.assertIsNone(more["31"]["pointer"])  # a servant's pointer is its foreman's plan

    def test_collect_to_plan_a_stale_pointer_and_a_free_field_end_to_end(self):
        with mock.patch.object(facts, "disk", return_value={"free_gb": 90.0, "used_pct": 95.0, "total_gb": 1000.0}):
            f = facts.collect(str(self.main), build=lambda path: False, measure=self.sizes, only={"03", "05", "06"},
                              lookup=lookup({"0001-x": "finished"}))
        self.assertEqual(f["cars"], [])
        self.assertGreater(f["now_ms"], NOW_MS / 10)
        p = planner.plan(f)
        self.assertEqual([(a["field"], a["action"]) for a in p["jobs"]["stale-pointers"]["actions"]], [("05", "clear-pointer")])
        self.assertEqual([(a["field"], a["action"]) for a in p["jobs"]["phase-1"]["actions"]], [("03", "muck-out")])
        self.assertEqual(sorted((a["field"], a["action"]) for a in p["jobs"]["phase-2"]["actions"]),
                         [("03", "trim"), ("06", "trim")], "D24: the free 03 is trimmed after its muck out")


if __name__ == "__main__":
    unittest.main()
