"""Prune's facts (facts.py; hal2 plan 0377 step 3): the fields, sessions, proof, disk and config. The CLIs are fakes
(`facts.call`), git runs on the farmer's scratch farm; nothing is removed, no real hal2-cli-* runs."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import facts
import mtm_scan
import worktree_farm
from test_farmer import NOW
from worktree_farm import NOW_MS


class Config(unittest.TestCase):
    def setUp(self):
        self.main = Path(tempfile.mkdtemp())
        (self.main / ".hal").mkdir()

    def write(self, text):
        (self.main / facts.CONFIG).write_text(text)

    def test_without_the_file_the_defaults(self):
        c = facts.config(str(self.main))
        self.assertEqual(c["source"], "defaults")
        self.assertEqual((c["threshold"], c["goal"]), ({"free_gb": 150, "used_pct": 90}, {"free_gb": 250, "used_pct": 85}))
        self.assertEqual(c["phases"], {"trim_session_less": True, "trim_idle_live": True, "trim": None})

    def test_the_file_overrides_key_by_key(self):
        self.write('[threshold]\nfree_gb = 100\n[phases]\ntrim_idle_live = false\ntrim = ["code/rust/target"]\n')
        c = facts.config(str(self.main))
        self.assertEqual(c["source"], "file")
        self.assertEqual(c["threshold"], {"free_gb": 100, "used_pct": 90})
        self.assertEqual(c["goal"]["free_gb"], 250)
        self.assertEqual(c["phases"], {"trim_session_less": True, "trim_idle_live": False, "trim": ["code/rust/target"]})

    def test_invalid_values_are_all_named(self):
        self.write('[threshold]\nfree_gb = "many"\nused_pct = 120\nnope = 1\n[phases]\ntrim_session_less = 1\n[x]\na = 1\n')
        with self.assertRaises(facts.FactsError) as e:
            facts.config(str(self.main))
        text = str(e.exception)
        for part in ("threshold.free_gb", "threshold.used_pct: at most 100", "unknown key threshold.nope",
                     "phases.trim_session_less: true or false", "unknown section [x]"):
            self.assertIn(part, text)

    def test_a_trim_path_stays_inside_the_field_and_outside_the_protected_folders(self):
        for bad in ('"/etc"', '"../x"', '".git/hooks"', '"plans/0001"', '".hal/cleanup"', '""', '"a", 3'):
            self.write(f"[phases]\ntrim = [{bad}]\n")
            with self.assertRaises(facts.FactsError, msg=bad):
                facts.config(str(self.main))

    def test_a_goal_less_strict_than_the_threshold_is_refused(self):
        self.write("[goal]\nfree_gb = 100\n")
        with self.assertRaises(facts.FactsError) as e:
            facts.config(str(self.main))
        self.assertIn("at least as strict", str(e.exception))
        self.write("[goal]\nused_pct = 95\n")
        with self.assertRaises(facts.FactsError):
            facts.config(str(self.main))

    def test_a_broken_toml_is_an_error(self):
        self.write("[threshold\n")
        with self.assertRaises(facts.FactsError):
            facts.config(str(self.main))

    def test_threshold_and_goal(self):
        c = facts.config(str(self.main))
        self.assertTrue(facts.short_of_space({"free_gb": 149, "used_pct": 50}, c))
        self.assertTrue(facts.short_of_space({"free_gb": 500, "used_pct": 91}, c))
        self.assertFalse(facts.short_of_space({"free_gb": 150, "used_pct": 90}, c))
        self.assertFalse(facts.goal_met({"free_gb": 249, "used_pct": 50}, c))
        self.assertFalse(facts.goal_met({"free_gb": 300, "used_pct": 86}, c))
        self.assertTrue(facts.goal_met({"free_gb": 250, "used_pct": 85}, c))


class Disk(unittest.TestCase):
    def test_free_gb_and_used_percent(self):
        usage = mock.Mock(total=1000 * 10**9, used=880 * 10**9, free=120 * 10**9)
        with mock.patch.object(facts.shutil, "disk_usage", return_value=usage):
            self.assertEqual(facts.disk("/x"), {"free_gb": 120.0, "used_pct": 88.0, "total_gb": 1000.0})

    def test_a_missing_program_is_a_tool_missing_a_failing_one_is_empty(self):
        with self.assertRaises(facts.ToolMissing):
            facts.call(["hal2-no-such-tool-for-prune-tests"])
        self.assertEqual(facts.call(["python3", "-c", "import sys; print('x'); sys.exit(3)"]), "")


class Farm(worktree_farm.MarkedSlots):
    """The scratch farm behind fake CLIs: `worktree list --json`, `agents list --json`, `worktree queue --json`."""

    def setUp(self):
        super().setUp()
        self.agents, self.queue = [], {}
        patcher = mock.patch.object(facts, "call", side_effect=self.cli)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sizes = lambda main, fs: {f["slot"]: {"bytes": 1000, "files": 1, "lower_bound": False} for f in fs}

    def worktrees(self):
        rows = [{"name": "main", "path": str(self.main), "main": True, "branch": "main"}]
        for w in mtm_scan.worktrees(str(self.main)):
            rows.append({"name": Path(w["path"]).name, "path": w["path"], "main": False, "branch": w.get("branch")})
        return {"worktrees": rows}

    def cli(self, argv, cwd=None, timeout=120):
        if argv[:3] == ["hal2-cli-git", "worktree", "list"]:
            return json.dumps(self.worktrees())
        if argv[:3] == ["hal2-cli-git", "worktree", "queue"]:
            return json.dumps(self.queue)
        if argv[:2] == ["hal2-cli-agents", "list"]:
            return json.dumps(self.agents)
        raise AssertionError(f"unexpected call {argv}")


class Fields(Farm):
    def test_only_numbered_fields_with_their_kind_and_head(self):
        fs = facts.fields(str(self.main))
        self.assertEqual([f["slot"] for f in fs], ["02", "03", "04", "05", "06", "07", "12", "13", "14", "31", "32", "33"])
        kinds = {f["slot"]: f["kind"] for f in fs}
        self.assertEqual((kinds["03"], kinds["13"], kinds["31"]), ("keeper", "foreman", "servant"))
        self.assertTrue(all(len(f["head"]) == 40 and f["path"].endswith("/" + f["slot"]) for f in fs))

    def test_no_json_is_an_error(self):
        with mock.patch.object(facts, "call", return_value="not json"):
            with self.assertRaises(facts.FactsError):
                facts.fields(str(self.main))

    def test_agents_as_a_list_or_under_agents_and_their_sessions_per_field(self):
        rows = [{"pane_id": "%1", "checkout": str(self.base / "13"), "state": "idle", "since": 5},
                {"pane_id": "%2", "checkout": str(self.base / "13"), "state": "ended", "since": 6}]
        self.agents = rows
        self.assertEqual(facts.agents(str(self.main)), rows)
        self.agents = {"agents": rows}  # the real shape of `hal2-cli-agents list --json`
        got = facts.agents(str(self.main))
        self.assertEqual(got, rows)
        field = {"path": str(self.base / "13")}
        self.assertEqual(facts.session(field, got), [{"pane_id": "%1", "state": "idle", "since": 5}])
        self.assertEqual(facts.session({"path": str(self.base / "14")}, got), [])

    def test_an_unreadable_list_is_none_never_an_empty_list(self):
        for bad in ("", "not json", "{}", '{"agents": 3}'):
            with mock.patch.object(facts, "call", return_value=bad):
                self.assertIsNone(facts.agents(str(self.main)), bad)
        self.assertEqual(facts.session({"path": str(self.base / "13")}, None), [])

    def test_an_unreadable_list_refuses_every_field(self):
        fs = facts.fields(str(self.main))
        why = facts.proofs(fs, {}, None, NOW_MS, lambda path: False)
        self.assertTrue(why and all(w and "could not be read" in w for w in why.values()), why)


class Context(Farm):
    def test_the_queue_the_landing_and_the_open_questions(self):
        self.queue = {"queue": [{"slot": "13", "state": "waiting"}, {"slot": "14", "state": "active"},
                                {"slot": "03", "state": "waiting", "hold": {"reason": "reserved"}}]}
        log = self.data / "hal2/tollman/log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps({"at": NOW.isoformat(), "kind": "ask", "slot": "06"}) + "\n")
        ctx = facts.context(str(self.main), NOW)
        self.assertEqual(ctx["landing"], {"14", "03"})
        self.assertEqual(ctx["waiting"], {"13", "14", "03"})
        self.assertEqual(len(ctx["log"]), 1)
        self.assertEqual(ctx["farmer_log"], [])

    def test_the_proof_per_field_free_or_why_not(self):
        fs = [f for f in facts.fields(str(self.main)) if f["slot"] in ("03", "04", "13", "31", "32")]
        ctx = {"waiting": {"13"}, "landing": set(), "log": [], "farmer_log": []}
        why = facts.proofs(fs, ctx, [], NOW_MS, lambda path: False)
        self.assertIsNone(why["03"])
        self.assertIn("uncommitted", why["04"])
        self.assertIn("ticket", why["13"])
        self.assertIsNone(why["31"])
        self.assertIn("not in origin/02", why["32"])


class Collect(Farm):
    def test_the_facts_of_a_farm(self):
        since = int(time.time() * 1000) - 60_000  # collect reads the clock: a session active a minute ago
        self.agents = [{"pane_id": "%1", "checkout": str(self.base / "13"), "state": "idle", "since": since}]
        with mock.patch.object(facts, "disk", return_value={"free_gb": 90.0, "used_pct": 95.0, "total_gb": 1000.0}):
            f = facts.collect(str(self.main), NOW, build=lambda path: False, measure=self.sizes, only={"03", "13", "04"})
        self.assertEqual(f["disk"]["free_gb"], 90.0)
        self.assertEqual(f["config"]["source"], "defaults")
        by = {x["slot"]: x for x in f["fields"]}
        self.assertEqual(sorted(by), ["03", "04", "13"])
        self.assertTrue(by["03"]["free"] and by["03"]["proof"] is None)
        self.assertFalse(by["04"]["free"])
        self.assertEqual(by["13"]["sessions"], [{"pane_id": "%1", "state": "idle", "since": since}])
        self.assertIn("active in the last", by["13"]["proof"])
        self.assertEqual(by["03"]["size"]["bytes"], 1000)

    def test_cached_sizes_asks_the_measure_for_cache_hits_only(self):
        seen = []
        def measure(main, fs, **kw):
            seen.append(kw)
            return {f["slot"]: None for f in fs}
        f = facts.collect(str(self.main), NOW, build=lambda path: False, measure=measure, only={"03"}, cached_sizes=True)
        facts.collect(str(self.main), NOW, build=lambda path: False, measure=measure, only={"03"})
        self.assertEqual((seen, f["fields"][0]["size"]), ([{"cached_only": True}, {}], None))


if __name__ == "__main__":
    unittest.main()
