"""Prune's plan (plan.py; hal2 plan 0377 step 4): one test per rule of the brief's Must 5 and the scenarios PR1-PR18,
PR23-PR25 on hand-built facts. Pure: no git, no CLI, fast."""

import copy
import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import facts
import plan as planner

NOW = 1_800_000_000_000.0  # ms
MIN = 60_000
GB = 10**9


def sess(minutes_ago=120, state="idle", pane="%1"):
    return {"pane_id": pane, "state": state, "since": NOW - minutes_ago * MIN}


def field(slot, free=False, proof="2 commit(s) not on origin/main", size=None, sessions=(), **more):
    kind = "keeper" if int(slot) < 10 else "servant" if int(slot) >= 30 else "foreman"
    f = {"slot": slot, "path": f"/w/{slot}", "kind": kind, "branch": slot, "sessions": list(sessions), "free": free,
         "proof": None if free else proof, "size": size and {"bytes": size, "files": 1, "lower_bound": False},
         "pointer": None, "unsaved": None, "lead": None, "hold": None, "building": False}
    return {**f, **more}


def farm(*fields, free_gb=120.0, used_pct=70.0, cars=(), **phases):
    cfg = copy.deepcopy(facts.DEFAULTS)
    cfg["phases"].update(phases)
    return {"main": "/w/main", "now_ms": NOW, "disk": {"free_gb": free_gb, "used_pct": used_pct, "total_gb": 1000.0},
            "config": {"source": "defaults", **cfg}, "cars": list(cars), "fields": list(fields)}


def acts(p, job):
    return [(a["field"], a["action"]) for a in p["jobs"][job]["actions"]]


class Free(unittest.TestCase):
    def test_pr1_a_free_field_10_99_is_removed_in_phase_1(self):
        p = planner.plan(farm(field("23", free=True, size=4 * GB), free_gb=400, used_pct=50))
        self.assertEqual(acts(p, "phase-1"), [("23", "remove")])
        a = p["jobs"]["phase-1"]["actions"][0]
        self.assertEqual((a["stop_sessions"], a["bytes"], a["why"]), ([], 4 * GB, "free by the proof"))
        self.assertEqual(p["left"], [])

    def test_pr2_a_free_field_with_an_idle_session_stops_it_first(self):
        p = planner.plan(farm(field("24", free=True, sessions=[sess(60, pane="%9")])))
        a = p["jobs"]["phase-1"]["actions"][0]
        self.assertEqual((a["action"], a["stop_sessions"]), ("remove", ["%9"]))
        self.assertIn("would stop session %9", planner.describe(a))

    def test_pr3_a_field_not_free_is_left_with_the_proofs_reason(self):
        p = planner.plan(farm(field("25", free=False), free_gb=400, used_pct=50))
        self.assertEqual(acts(p, "phase-1"), [])
        self.assertEqual(p["left"], [{"field": "25", "why": "2 commit(s) not on origin/main"}])

    def test_phase_1_runs_on_a_fine_disk_and_a_short_one(self):
        for free_gb in (400, 90):
            p = planner.plan(farm(field("23", free=True), free_gb=free_gb))
            self.assertEqual(acts(p, "phase-1"), [("23", "remove")], free_gb)

    def test_pr9_a_servant_below_30_stays_whatever_its_state(self):
        p = planner.plan(farm(field("12", proof="a servant's worktree below 30 (foreman 02) is never pruned"),
                              free_gb=400))
        self.assertEqual(acts(p, "phase-1"), [])
        self.assertIn("below 30", p["left"][0]["why"])


class StalePointer(unittest.TestCase):
    def ptr(self, state, unsaved=(), **more):
        return field("13", pointer={"plan": "0149-x", "state": state}, unsaved=list(unsaved),
                     proof="the CURRENT_PLAN pointer names 0149-x", **more)

    def test_pr4_a_finished_plan_with_nothing_off_main_is_cleared_and_rechecked(self):
        p = planner.plan(farm(self.ptr("finished")))
        (a,) = p["jobs"]["stale-pointers"]["actions"]
        self.assertEqual((a["field"], a["action"], a["plan"], a["recheck"]), ("13", "clear-pointer", "0149-x", True))
        self.assertIn("0149-x cleared: finished", a["why"])
        self.assertEqual(p["left"], [])

    def test_pr4_a_cleared_field_is_not_planned_again_on_its_old_proof(self):
        p = planner.plan(farm(self.ptr("finished")))
        for job in ("phase-1", "phase-2", "phase-3"):
            self.assertEqual(acts(p, job), [], job)

    def test_pr6_a_pointer_to_a_missing_plan_is_treated_as_finished(self):
        p = planner.plan(farm(self.ptr("missing")))
        self.assertEqual(acts(p, "stale-pointers"), [("13", "clear-pointer")])
        self.assertIn("missing", p["jobs"]["stale-pointers"]["actions"][0]["why"])

    def test_pr5_the_pointer_stays_when_the_plan_is_open_unknown_or_the_field_has_work_or_a_session(self):
        cases = {"open plan": self.ptr("open"), "unknown plan": self.ptr("unknown"),
                 "commits off main": self.ptr("finished", ["2 commit(s) not on origin/main"]),
                 "uncommitted": self.ptr("finished", ["uncommitted changes"]),
                 "live session": self.ptr("finished", sessions=[sess()]),
                 "not checked": field("13", pointer={"plan": "0149-x", "state": "finished"}, unsaved=None)}
        for name, f in cases.items():
            p = planner.plan(farm(f))
            self.assertEqual(acts(p, "stale-pointers"), [], name)
            self.assertEqual(p["jobs"]["stale-pointers"]["skipped"], "no stale pointer", name)

    def test_pr4_cleared_fields_are_ordered_like_every_job(self):
        a = self.ptr("finished", size=GB)
        b = field("14", pointer={"plan": "p", "state": "finished"}, unsaved=[], size=9 * GB)
        p = planner.plan(farm(a, b))
        self.assertEqual([x["field"] for x in p["jobs"]["stale-pointers"]["actions"]], ["14", "13"])


class Servants(unittest.TestCase):
    def lead(self, missing, at_min_ago=120, **more):
        return {"slot": "01", "at": (NOW - at_min_ago * MIN) / 1000, "missing": missing, **more}

    def test_pr7_a_free_servant_in_its_foremans_branch_is_removed(self):
        p = planner.plan(farm(field("52", free=True, lead=self.lead([]))))
        a = p["jobs"]["phase-1"]["actions"][0]
        self.assertEqual((a["action"], a["servant_of"]), ("remove", "01"))

    def test_pr8_a_servant_not_in_its_foremans_branch_is_an_ask_never_a_removal(self):
        miss = ["HEAD: 3 commit(s) not in origin/01"]
        p = planner.plan(farm(field("40", lead=self.lead(miss), proof="; ".join(miss)), free_gb=400))
        (a,) = p["jobs"]["phase-1"]["actions"]
        self.assertEqual((a["action"], a["foreman"]), ("ask", "01"))
        self.assertEqual(planner.describe(a), "ask the foreman of field 01 about field 40: HEAD: 3 commit(s) not in origin/01")
        self.assertEqual(p["left"], [])

    def test_pr8_no_ask_while_the_foreman_still_uses_the_field(self):
        miss = ["HEAD: 3 commit(s) not in origin/01"]
        cases = {"fresh LEAD": self.lead(miss, at_min_ago=10), "bad marker": {"bad": "plans/LEAD: broken"}}
        for name, lead in cases.items():
            p = planner.plan(farm(field("40", lead=lead)))
            self.assertEqual(acts(p, "phase-1"), [], name)
        for name, extra in {"session": {"sessions": [sess()]}, "ticket": {"hold": "it has a merge queue ticket"}}.items():
            p = planner.plan(farm(field("40", lead=self.lead(miss), **extra)))
            self.assertEqual(acts(p, "phase-1"), [], name)

    def test_pr8_the_ask_field_is_still_trimmed_when_the_disk_is_short(self):
        miss = ["HEAD: 3 commit(s) not in origin/01"]
        p = planner.plan(farm(field("40", lead=self.lead(miss)), free_gb=100))
        self.assertEqual(acts(p, "phase-1"), [("40", "ask")])
        self.assertEqual(acts(p, "phase-2"), [("40", "trim")])


class TrainBuilding(unittest.TestCase):
    """Plan 0472 D1: no trim and no muck out while a workqueue hold stands; a removal goes on; trims return after it."""
    WAIT = "deferred: train building (hold h1 of field 31, holding)"

    def facts(self, busy=None):
        fs = [field("04", sizes=None), field("05", sessions=[sess(120)]), field("03", free=True), field("23", free=True)]
        return {**farm(*fs, free_gb=100), "busy": busy}

    def test_no_trim_and_no_muck_out_while_a_hold_is_active(self):
        p = planner.plan(self.facts(self.WAIT))
        for job in ("phase-2", "phase-3"):
            self.assertEqual((acts(p, job), p["jobs"][job]["skipped"]), ([], self.WAIT), job)
        self.assertEqual(acts(p, "phase-1"), [("23", "remove")], "the removal needs no walk")
        self.assertEqual(p["busy"], self.WAIT)
        self.assertIn(("03", self.WAIT), [(x["field"], x["why"]) for x in p["left"]])

    def test_trims_and_the_muck_out_return_when_the_hold_ends(self):
        p = planner.plan(self.facts(None))
        self.assertEqual(acts(p, "phase-1"), [("03", "muck-out"), ("23", "remove")])
        self.assertTrue(acts(p, "phase-2") or acts(p, "phase-3"))


class Busy(unittest.TestCase):
    def test_pr10_a_building_or_busy_field_is_trimmed_in_no_phase(self):
        fs = [field("26", building=True), field("27", sessions=[sess(120, "working")]),
              field("28", sessions=[sess(120, "blocked")])]
        p = planner.plan(farm(*fs, free_gb=100))
        for job in ("phase-1", "phase-2", "phase-3"):
            self.assertEqual(acts(p, job), [], job)
        self.assertEqual({x["field"] for x in p["left"]}, {"26", "27", "28"})

    def test_pr11_a_field_in_the_queue_is_neither_removed_nor_trimmed(self):
        fs = [field("27", hold="it has a merge queue ticket or the boss paused it"),
              field("29", sessions=[sess(120)], hold="it has a merge queue ticket or the boss paused it")]
        p = planner.plan(farm(*fs, free_gb=100))
        for job in ("phase-1", "phase-2", "phase-3"):
            self.assertEqual(acts(p, job), [], job)


class Threshold(unittest.TestCase):
    fs = (field("13", size=5 * GB), field("14", size=9 * GB), field("15", size=GB, sessions=[sess(120)]))

    def test_pr12_a_fine_disk_skips_phases_2_and_3(self):
        p = planner.plan(farm(*self.fs, free_gb=400, used_pct=70))
        self.assertFalse(p["short"])
        self.assertEqual(p["jobs"]["phase-2"]["skipped"], "disk fine (400 GB free)")
        self.assertEqual(p["jobs"]["phase-3"]["skipped"], "disk fine (400 GB free)")
        self.assertEqual((acts(p, "phase-2"), acts(p, "phase-3")), ([], []))

    def test_pr13_under_150_gb_free_or_over_90_percent_phase_2_trims_session_less_fields_biggest_first(self):
        for free_gb, used in ((120, 70), (400, 91), (149.9, 50)):
            p = planner.plan(farm(*self.fs, free_gb=free_gb, used_pct=used))
            self.assertTrue(p["short"], (free_gb, used))
            self.assertEqual(acts(p, "phase-2"), [("14", "trim"), ("13", "trim")])
            self.assertTrue(p["jobs"]["phase-2"]["until_goal"])

    def test_the_edge_is_not_short(self):
        self.assertFalse(planner.plan(farm(*self.fs, free_gb=150, used_pct=90))["short"])

    def test_pr14_the_goal_is_carried_so_a_started_phase_goes_on_to_it(self):
        p = planner.plan(farm(*self.fs, free_gb=120))
        self.assertEqual(p["goal"], {"free_gb": 250, "used_pct": 85})
        self.assertFalse(p["goal_met"])
        self.assertTrue(p["jobs"]["phase-3"]["until_goal"])
        self.assertTrue(planner.plan(farm(free_gb=260, used_pct=80))["goal_met"])

    def test_between_threshold_and_goal_nothing_is_started(self):
        p = planner.plan(farm(*self.fs, free_gb=200, used_pct=88))
        self.assertFalse(p["short"])
        self.assertEqual(acts(p, "phase-2"), [])

    def test_a_phase_switched_off_in_the_config_says_so(self):
        p = planner.plan(farm(*self.fs, free_gb=100, trim_session_less=False, trim_idle_live=False))
        self.assertEqual(p["jobs"]["phase-2"]["skipped"], "switched off in .hal/prune.toml (trim_session_less)")
        self.assertEqual(p["jobs"]["phase-3"]["skipped"], "switched off in .hal/prune.toml (trim_idle_live)")

    def test_pr23_without_a_trim_list_the_cleanup_skills_own_set_pr24_a_listed_path_is_carried(self):
        a = planner.plan(farm(*self.fs, free_gb=100))["jobs"]["phase-2"]["actions"][0]
        self.assertIsNone(a["paths"])
        self.assertIn("cleanup's own set", planner.describe(a))
        trim = ["code/rust/target", "code/typescript/node_modules"]
        b = planner.plan(farm(*self.fs, free_gb=100, trim=trim))["jobs"]["phase-2"]["actions"][0]
        self.assertEqual(b["paths"], trim)


class IdleLive(unittest.TestCase):
    def test_pr15_phase_3_trims_an_idle_live_field(self):
        p = planner.plan(farm(field("03", sessions=[sess(40)], size=GB), free_gb=100))
        self.assertEqual(acts(p, "phase-3"), [("03", "trim")])
        self.assertEqual(acts(p, "phase-2"), [])

    def test_pr15_not_idle_when_active_busy_building_or_in_the_queue(self):
        fs = [field("04", sessions=[sess(5)]), field("05", sessions=[sess(40, "working")]),
              field("06", sessions=[sess(40)], building=True), field("07", sessions=[sess(40)], hold="ticket"),
              field("08", sessions=[sess(40), sess(10, pane="%2")])]
        p = planner.plan(farm(*fs, free_gb=100))
        self.assertEqual(acts(p, "phase-3"), [])

    def test_the_idle_window_is_thirty_minutes(self):
        p = planner.plan(farm(field("04", sessions=[sess(29)]), field("05", sessions=[sess(30)]), free_gb=100))
        self.assertEqual(acts(p, "phase-3"), [("05", "trim")])

    def test_a_field_removed_in_phase_1_is_not_trimmed_again(self):
        p = planner.plan(farm(field("24", free=True, sessions=[sess(60)]), free_gb=100))
        self.assertEqual(acts(p, "phase-1"), [("24", "remove")])
        self.assertEqual(acts(p, "phase-3"), [])


class Order(unittest.TestCase):
    def test_pr16_the_jobs_come_in_the_briefs_order(self):
        p = planner.plan(farm(field("13", size=GB), free_gb=100))
        self.assertEqual(list(p["jobs"]), ["stale-pointers", "phase-1", "phase-2", "phase-3", "responses"])
        self.assertEqual(list(p["jobs"]), list(planner.JOBS))

    def test_pr16_the_last_trains_cars_first_then_the_biggest_then_by_slot(self):
        fs = [field(s, free=True, size=n) for s, n in (("20", 5 * GB), ("21", 9 * GB), ("22", GB), ("23", 5 * GB),
                                                       ("24", 2 * GB))]
        p = planner.plan(farm(*fs, cars=["24", "22"]))
        self.assertEqual([a["field"] for a in p["jobs"]["phase-1"]["actions"]], ["24", "22", "21", "20", "23"])

    def test_pr16_the_same_order_in_a_trimming_phase(self):
        fs = [field(s, size=n) for s, n in (("13", GB), ("14", 8 * GB), ("15", 3 * GB))]
        p = planner.plan(farm(*fs, cars=["13"], free_gb=100))
        self.assertEqual([a["field"] for a in p["jobs"]["phase-2"]["actions"]], ["13", "14", "15"])

    def test_pr18_an_unknown_size_counts_by_its_lower_bound_and_is_marked(self):
        big = field("31", size=None)
        big["size"] = {"bytes": 7 * GB, "files": 9, "lower_bound": True}
        fs = [big, field("32", size=5 * GB), field("33", size=None)]
        p = planner.plan(farm(*fs, free_gb=100))
        got = p["jobs"]["phase-2"]["actions"]
        self.assertEqual([a["field"] for a in got], ["31", "32", "33"])
        self.assertEqual([a["lower_bound"] for a in got], [True, False, False])
        self.assertIn("≥ 7.0 GB", planner.describe(got[0]))


class Keepers(unittest.TestCase):
    def test_pr17_a_free_field_00_09_is_mucked_out_never_removed(self):
        for sessions in ([], [sess(600)], [sess(1)]):
            p = planner.plan(farm(field("05", free=True, sessions=sessions, size=GB)))
            self.assertEqual(acts(p, "phase-1"), [("05", "muck-out")])
            self.assertNotIn("remove", [a["action"] for j in p["jobs"].values() for a in j["actions"]])

    def test_pr17_no_job_ever_removes_a_field_00_09(self):
        fs = [field(f"0{n}", free=bool(n % 2), sessions=[sess(60)] if n % 3 else [], size=n * GB) for n in range(10)]
        p = planner.plan(farm(*fs, free_gb=90))
        removed = [a["field"] for j in p["jobs"].values() for a in j["actions"] if a["action"] == "remove"]
        self.assertEqual(removed, [])

    def test_pr17_in_phases_2_and_3_a_field_00_09_is_only_trimmed(self):
        fs = [field("02", size=GB), field("03", sessions=[sess(90)], size=2 * GB)]
        p = planner.plan(farm(*fs, free_gb=100))
        self.assertEqual((acts(p, "phase-2"), acts(p, "phase-3")), ([("02", "trim")], [("03", "trim")]))

    def test_d24_a_free_session_less_00_09_is_mucked_out_then_trimmed_in_phase_2_when_short(self):
        fs = [field("05", free=True, size=GB), field("06", free=True, sessions=[sess(90)], size=GB)]
        p = planner.plan(farm(*fs, free_gb=100))
        self.assertEqual(acts(p, "phase-1"), [("05", "muck-out"), ("06", "muck-out")])
        self.assertEqual((acts(p, "phase-2"), acts(p, "phase-3")), ([("05", "trim")], [("06", "trim")]))
        self.assertEqual(acts(planner.plan(farm(*fs, free_gb=400)), "phase-2"), [], "a fine disk trims nothing")

    def test_pr17_a_stale_pointer_in_00_09_is_cleared_then_rechecked(self):
        p = planner.plan(farm(field("04", pointer={"plan": "x", "state": "finished"}, unsaved=[])))
        self.assertEqual(acts(p, "stale-pointers"), [("04", "clear-pointer")])


class OnlyFields(unittest.TestCase):
    def test_field_limits_every_job_and_the_left_list(self):
        fs = [field("20", free=True), field("21", free=True), field("22", size=GB), field("23")]
        p = planner.plan(farm(*fs, free_gb=100), only={"21", "22"})
        self.assertEqual(acts(p, "phase-1"), [("21", "remove")])
        self.assertEqual(acts(p, "phase-2"), [("22", "trim")])
        self.assertEqual(p["left"], [])

    def test_field_naming_no_field_plans_nothing(self):
        p = planner.plan(farm(field("20", free=True)), only={"99"})
        self.assertEqual([a for j in p["jobs"].values() for a in j["actions"]], [])


class Pure(unittest.TestCase):
    def test_pr25_the_plan_changes_nothing_and_is_the_same_twice_and_reads_as_text(self):
        f = farm(field("23", free=True, sessions=[sess(60)]), field("13", size=GB), field("05", free=True),
                 field("40", pointer={"plan": "p", "state": "finished"}, unsaved=[]), free_gb=100)
        before = copy.deepcopy(f)
        p = planner.plan(f)
        self.assertEqual(f, before)
        self.assertEqual(p, planner.plan(f))
        text = "\n".join(planner.lines(p))
        for part in ("disk: 100 GB free", "stale-pointers:", "would clear 40", "would stop session %1, remove 23",
                     "would muck out 05", "phase-2:", "would trim 13"):
            self.assertIn(part, text)

    def test_the_clock_comes_from_the_facts_or_the_argument(self):
        f = farm(field("04", sessions=[sess(40)]), free_gb=100)
        self.assertEqual(acts(planner.plan(f), "phase-3"), [("04", "trim")])
        self.assertEqual(acts(planner.plan(f, now_ms=NOW - 30 * MIN), "phase-3"), [])


if __name__ == "__main__":
    unittest.main()
