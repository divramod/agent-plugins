"""The disk watermark's safe responses (responses.py; hal2 plan 0472 step 2, D2): `tart prune` of Tart's OCI cache and
the caches `.hal/prune.toml` lists, planned with their measured size only on a short disk and while no train builds,
run only while the disk is still above the goal, never a pattern, a field or a VM. The tart here is a fake program: the
real one is never called, no real folder is deleted."""

import copy
import json
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import executor
import facts
import fake_clis
import plan as planner
import responses
from fake_clis import jobs, parse
from test_executor import GOAL, SHORT
from test_plan import farm, field

FAKE_TART = "#!/bin/sh\necho \"$@\" >> \"$0.calls\"\nrm -rf \"$TART_FAKE_CACHE\"/*\n"


def with_responses(found, items):
    return {**found, "responses": items}


TART = {"field": "tart-cache", "action": "tart-prune", "target": "/t/cache", "bytes": 30 * 10**9, "lower_bound": False,
        "older_than_days": 7, "why": "Tart's caches"}
CACHE = {"field": "cache /c/x", "action": "cache-clear", "target": "/c/x", "bytes": 2 * 10**9, "lower_bound": False,
         "why": "listed"}


class Planning(unittest.TestCase):
    def acts(self, p):
        return [(a["field"], a["action"]) for a in p["jobs"]["responses"]["actions"]]

    def test_planned_with_their_size_biggest_first_only_on_a_short_disk(self):
        p = planner.plan(with_responses(farm(field("13"), free_gb=100, used_pct=91), [CACHE, TART]))
        self.assertEqual(self.acts(p), [("tart-cache", "tart-prune"), ("cache /c/x", "cache-clear")])
        self.assertEqual(p["jobs"]["responses"]["actions"][0]["bytes"], 30 * 10**9)
        self.assertTrue(p["jobs"]["responses"]["until_goal"])
        fine = planner.plan(with_responses(farm(field("13"), free_gb=400, used_pct=70), [TART]))
        self.assertEqual((self.acts(fine), fine["jobs"]["responses"]["skipped"]), ([], "disk fine (400 GB free)"))

    def test_between_the_warning_and_the_threshold_nothing_is_deleted(self):
        p = planner.plan(with_responses(farm(field("13"), free_gb=300, used_pct=87), [TART]))
        self.assertEqual(self.acts(p), [])

    def test_never_while_a_train_builds(self):
        wait = "deferred: train building (hold h1 of field 31, holding)"
        p = planner.plan({**with_responses(farm(field("13"), used_pct=93), [TART]), "busy": wait})
        self.assertEqual((self.acts(p), p["jobs"]["responses"]["skipped"]), ([], wait))

    def test_a_missing_tart_is_said_and_skipped(self):
        gone = {"field": "tart-cache", "action": "missing", "why": "tart is not installed here: skipped"}
        p = planner.plan(with_responses(farm(field("13"), used_pct=93), [gone]))
        job = p["jobs"]["responses"]
        self.assertEqual((job["actions"], job["skipped"], job["notes"]), ([], gone["why"], [gone["why"]]))
        self.assertIn("  note: tart is not installed here: skipped", planner.lines(p))

    def test_the_plan_text_names_the_command(self):
        p = planner.plan(with_responses(farm(field("13"), used_pct=93), [TART, CACHE]))
        text = "\n".join(planner.lines(p))
        self.assertIn("would run tart prune --entries caches --older-than=7 (30.0 GB): Tart's caches", text)
        self.assertIn("would clear /c/x (2.0 GB): listed", text)


class Config(unittest.TestCase):
    def test_caches_default_to_none_and_a_pattern_or_a_non_list_is_refused(self):
        self.assertEqual(facts.DEFAULTS["caches"]["paths"], [])
        self.assertEqual(facts.bad_value("caches", "paths", ["/a/b/c"]), None)
        self.assertIn("no pattern", facts.bad_value("caches", "paths", ["/a/*/c"]))
        self.assertEqual(facts.bad_value("caches", "paths", "/a/b/c"), "a list of folders")

    def test_refused_paths(self):
        guard = ["/w/main", "/w/13"]
        for path in ("/", "/Users", "/w/main", "/w/13/target", "/w", "~", "relative/x/y"):
            self.assertTrue(responses.refusal(path, guard), path)
        self.assertIsNone(responses.refusal("/var/cache/x", guard))


class Run(fake_clis.Farm):
    def setUp(self):
        super().setUp()
        self.home = self.tmp / "tart-home"
        self.cache = self.home / "cache"
        self.cache.mkdir(parents=True)
        (self.cache / "image").write_text("x" * 5000)
        self.vms = self.home / "vms"
        self.vms.mkdir()
        (self.vms / "keep").write_text("vm")
        bin_dir = self.tmp / "fake-tart"
        bin_dir.mkdir()
        self.tart = bin_dir / "tart"
        self.tart.write_text(FAKE_TART)
        self.tart.chmod(0o755)
        self.extra = self.tmp / "extra" / "caches" / "pip"
        self.extra.mkdir(parents=True)
        (self.extra / "pkg").write_text("y" * 100)
        env = mock.patch.dict("os.environ", {"TART_FAKE_CACHE": str(self.cache)})
        env.start()
        self.addCleanup(env.stop)

    def tart_calls(self):
        f = self.tart.parent / "tart.calls"
        return f.read_text().splitlines() if f.exists() else []

    def config(self, text=""):
        (self.main / ".hal").mkdir(exist_ok=True)
        (self.main / ".hal/prune.toml").write_text(text)

    def test_a_short_disk_runs_tart_prune_for_caches_only_never_a_vm(self):
        self.disk = dict(SHORT)
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        self.assertEqual(jobs(lines)[-2:], ["responses", "report"])
        self.assertEqual(self.tart_calls(), ["prune --entries caches --older-than=7"])
        self.assertEqual([(s[0], s[1]) for s in parse(lines)["responses"]], [("response tart-cache", "success")])
        self.assertTrue((self.vms / "keep").exists(), "a local VM is never touched")

    def test_the_measured_size_is_in_the_dry_run_and_nothing_changes(self):
        self.disk = dict(SHORT)
        code, lines = self.prune(dry=True)
        self.assertEqual(code, 0, lines)
        self.assertTrue(any(x.startswith("would run tart prune --entries caches --older-than=7 (8.2 KB): Tart's OCI and IPSW "
                            "caches unused for 7 days") for x in lines), lines)  # allocated bytes: two 4 KB blocks
        self.assertEqual(self.tart_calls(), [])
        self.assertTrue((self.cache / "image").exists())

    def test_a_fine_disk_and_a_disk_between_warning_and_threshold_run_no_response(self):
        for disk in (None, {"free_gb": 300.0, "used_pct": 87.0, "total_gb": 1000.0}):
            self.disk = disk or self.disk
            _, lines = self.prune()
            self.assertEqual(parse(lines)["responses"], [])
        self.assertEqual(self.tart_calls(), [])

    def test_still_above_the_goal_only_responses_after_the_trims_stop_at_the_goal(self):
        self.disk = dict(SHORT)
        reads = iter([SHORT, SHORT, GOAL])  # run start, the responses' gate, before the first response
        with mock.patch.object(facts, "disk", side_effect=lambda main: dict(next(reads, GOAL))):
            _, lines = self.prune()
        self.assertIn("stopped: goal met (300 GB free, 70% used)", lines)
        self.assertEqual(self.tart_calls(), [], "the goal was met: nothing deleted")

    def test_never_while_a_train_builds_also_when_it_starts_mid_run(self):
        self.disk = dict(SHORT)
        self.busy = "deferred: train building (hold h1 of field 31, holding)"
        _, lines = self.prune()
        self.assertIn(f"skipped: {self.busy}", lines)
        self.assertEqual(self.tart_calls(), [])
        answers = iter([None, self.busy])  # free for the plan, a hold when the response is about to run
        self.busy = None
        with mock.patch.object(fake_clis.busy, "reason", side_effect=lambda main: next(answers, self.busy_text)) as m:
            self.busy_text = "deferred: train building (hold h2 of field 31, holding)"
            _, lines = self.prune()
        self.assertTrue(any(x.startswith("stopped: deferred: train building") for x in lines), lines)
        self.assertEqual(self.tart_calls(), [])

    def test_a_listed_cache_is_cleared_and_its_folder_stays_a_field_is_refused(self):
        self.disk = dict(SHORT)
        self.tart = None  # no tart here
        self.add("23")
        self.config(f'[caches]\npaths = ["{self.extra}", "{self.base}"]\n')
        _, lines = self.prune()
        self.assertEqual(list(self.extra.iterdir()), [], "the contents went")
        self.assertTrue(self.extra.is_dir(), "the folder stays")
        self.assertTrue(any("tart is not installed here: skipped" in x for x in lines), "a missing tart is said")
        self.assertTrue(any("not touched: holds or is inside" in x for x in lines), "a path over the fields is refused")
        self.assertEqual([(s[0], s[1]) for s in parse(lines)["responses"]], [(f"response cache {self.extra}", "success")])

    def test_a_missing_tart_fails_nothing(self):
        self.disk = dict(SHORT)
        self.tart = None
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        self.assertIn("skipped: tart is not installed here: skipped", lines)

    def test_responses_only_runs_no_field_phase(self):
        self.disk = dict(SHORT)
        self.add("23")
        lines: list[str] = []
        code = executor.run(str(self.main), set(), False, executor.Out(lines.append), responses_only=True)
        self.assertEqual(code, 0, lines)
        self.assertEqual(jobs(lines), ["facts", "responses", "report"])
        self.assertTrue((self.base / "23").exists(), "no field phase ran")
        self.assertEqual(self.tart_calls(), ["prune --entries caches --older-than=7"])


if __name__ == "__main__":
    unittest.main()
