"""Hal2 plan 0480 step 02.02: a round reads `hal2-cli-agents list` once, `checks.runs` takes the round's one runs read,
and the frame merges from main only when origin's default branch moved. Whole rounds on test_tollman's farm."""
# enforces .adr/deterministic-first.md

import json
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import checks
import mtm_ci
import mtm_scan
import tick
import tollman
from gh_fake import FakeGh, run
from test_farmer import NOW, git
from test_tollman import Field

MFM = ["hal2-cli-git", "worktree", "merge-from-main"]
CHECK = {"event": "workflow_dispatch", "displayTitle": "[13] ci-check 0480 1/2"}


class Farm(Field):
    """test_tollman's Rounds farm (two waiting fields, real handlers, the queue is data), counting the agents lists and
    the merge-from-main calls."""

    def setUp(self):
        super().setUp()
        self.fields = {n: self.field(n) for n in ("07", "09")}
        for n, path in self.fields.items():
            self.commit(path, f"{n}.txt", n)
        self.queue = [{"slot": n, "position": i, "state": "waiting", "branch": n, "worktree": str(path), "seq": i + 1,
                       "pid": 0} for i, (n, path) in enumerate(self.fields.items())]
        self.lists, self.merges = 0, []
        real = tick.sh

        def answers(args, cwd=None):
            return {"queue": self.queue} if args[:3] == ["hal2-cli-git", "worktree", "queue"] else None

        def cli(*args, timeout=30):
            self.lists += args[0] == "list"
            return 0, "[]"

        def sh(argv, cwd, timeout=900):
            if argv[:3] == MFM:  # what the real one does: the default branch merged into the field
                self.merges.append(argv)
                real(["git", "merge", "-q", "--no-edit", "origin/main"], cwd, timeout)
            return (0, json.dumps({"status": "ok"})) if argv[0] == "hal2-cli-git" else real(argv, cwd, timeout)

        for p in (mock.patch.object(mtm_scan, "run_json", answers), mock.patch.object(tick, "sh", sh),
                  mock.patch.object(tick.deliver, "cli", cli),
                  mock.patch.object(tick.deliver, "send", lambda pane, text, s=None: None)):
            p.start()
            self.addCleanup(p.stop)
        self.call("mode", "timer")


class OneList(Farm):
    def test_a_whole_round_reads_the_agents_once_for_the_scan_and_the_wake(self):
        code, out = self.call("tick")
        self.assertEqual(code, 0, out)
        kinds = {e["kind"] for e in self.wm_log()}
        self.assertTrue({"waiter-gone", "ask-ack"} <= kinds, "the boss scanned and the round handed over its items")
        self.assertEqual(self.lists, 1, "context, the scan and the wake share one list")

    def test_the_scan_gets_the_rounds_list_and_an_unreadable_one_stays_unreadable(self):
        seen = []
        real = mtm_scan.snapshot

        def snapshot(*args, **kw):
            seen.append(kw.get("agents", mtm_scan.READ))
            return real(*args, **kw)

        with mock.patch.object(mtm_scan, "snapshot", snapshot):
            self.call("tick")
        self.assertEqual(seen, [[]], "the round's list, not mtm_scan.READ")
        ctx = lambda: tick.context(str(self.wm), str(self.main), {}, NOW, True, tollman.WIRING)  # noqa: E731
        self.assertEqual(ctx()["agents"], [], "readable and empty")
        with mock.patch.object(tick.deliver, "cli", return_value=(1, "")):
            self.assertEqual((ctx()["agents"], ctx()["agent_rows"]), (None, []), "failed: unreadable, never empty")


class RunsOfChecks(Field):
    def rows(self, *extra):
        return [run(5, "land/07", "2026-10-30T10:00:00Z", status="in_progress") | {"path": ".github/workflows/other.yml"},
                run(6, "13", "2026-10-30T10:01:00Z", status="in_progress") | CHECK | {"path": ".github/workflows/x.yml"},
                run(7, "13", "2026-10-30T10:02:00Z", status="in_progress") | CHECK | {"path": ".github/workflows/x.yml"},
                run(8, "land/09", "2026-10-30T10:03:00Z", status="in_progress"), *extra]

    def test_checks_runs_is_the_rounds_one_runs_read_filtered_by_the_workflow(self):
        gh = FakeGh(self.rows()).start(self)
        with mock.patch.object(checks, "workflow", return_value="x.yml"), mtm_ci.gh_runs.round(None):
            got = checks.runs(mtm_scan.run_json, "/m")
            self.assertEqual(checks.runs(mtm_scan.run_json, "/m"), got)
            self.assertEqual([r["databaseId"] for r in mtm_ci.runs_of(mtm_scan.run_json, "/m", run=gh.run)], [8])
        self.assertEqual([r["databaseId"] for r in got], [7, 6], "the workflow's runs, newest first")
        self.assertEqual([r["event"] for r in got], ["workflow_dispatch"] * 2)
        self.assertEqual([r["displayTitle"] for r in checks.unfinished_checks(got)], [CHECK["displayTitle"]] * 2)
        self.assertEqual(gh.runs_lists(), 1, "one runs read for checks and the landing lists of the round")
        self.assertFalse([c for c in gh.calls if c[1:3] == ["run", "list"]], "no gh run list")

    def test_no_answer_is_none(self):
        FakeGh(()).start(self)
        with mock.patch.object(mtm_scan, "run_json", return_value=None):
            self.assertIsNone(checks.runs(mtm_scan.run_json, "/m"))


class MergeFromMain(Farm):
    def push_to_origin(self, name):
        git(self.main, "pull", "-q", "--ff-only", "origin", "main")
        self.commit(self.main, name, name, push=True)

    def test_only_a_moved_origin_merges_and_a_failed_merge_is_tried_again(self):
        first = self.call("tick")[0]
        self.assertEqual((first, len(self.merges)), (0, 1), "the first round merges")
        self.call("tick")
        self.assertEqual(len(self.merges), 1, "origin did not move: no merge-from-main")
        self.assertEqual(json.loads((self.wm_state / "last-mfm.json").read_text())["schema"], 1)
        self.push_to_origin("moved.txt")
        self.call("tick")
        self.assertEqual(len(self.merges), 2, "origin moved: merged again")
        self.call("tick")
        self.assertEqual(len(self.merges), 2)
        self.push_to_origin("moved-2.txt")
        recorded = (self.wm_state / "last-mfm.json").read_text()
        ok = tick.sh

        def red(argv, cwd, timeout=900):
            return (1, '{"status": "conflict"}') if argv[:3] == MFM else ok(argv, cwd, timeout)

        with mock.patch.object(tick, "sh", red):
            self.call("tick")
        self.assertEqual(len(self.merges), 2, "the red merge did not reach the counting shell")
        self.assertEqual((self.wm_state / "last-mfm.json").read_text(), recorded, "a failed merge records nothing")
        self.call("tick")
        self.assertEqual(len(self.merges), 3, "and it is tried again the next round")
        self.assertNotEqual((self.wm_state / "last-mfm.json").read_text(), recorded)

    def test_a_dry_round_plans_the_merge_and_fetches_nothing(self):
        r = json.loads(self.call("tick", "--dry-run", "--json")[1])
        self.assertEqual([a["kind"] for a in r["planned"]][:1], ["stay-current"])
        self.assertEqual(self.merges, [])
        self.assertFalse((self.wm_state / "last-mfm.json").exists())

    def test_a_worktree_that_lost_the_default_branch_merges_again(self):
        self.call("tick")
        git(self.wm, "reset", "-q", "--hard", "HEAD~1")  # the recorded sha is no longer in HEAD
        self.call("tick")
        self.assertEqual(len(self.merges), 2)


if __name__ == "__main__":
    unittest.main()
