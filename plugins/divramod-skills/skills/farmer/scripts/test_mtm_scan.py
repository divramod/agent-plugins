import time
import unittest

import mtm_scan as scan
import test_farmer
import worktree_farm


def snap(**over):
    base = {
        "now": time.time(), "queue": [], "worktrees": [], "landings": [], "tests": {},
        "load": {"load1": 4.0, "cores": 10, "per_core": 0.4}, "paused": None,
    }
    base.update(over)
    return base


class FailingTests(unittest.TestCase):
    def test_swift_testing_xctest_cargo_and_nextest_names(self):
        msg = (
            "libs.Hal2Kit test-unit (.hal/hooks.toml) failed with exit code 1\n"
            "✘ Test everyPlaceAtOnceStaysResponsive() failed after 20.269 seconds with 1 issue.\n"
            "Test Case '-[Hal2Tests.WebHostTests servesThePage]' failed (10.1 seconds).\n"
            "    test landings::tests::follows_landings_as_they_go ... FAILED\n"
            "  TRY 3 FAIL [  28.638s] (4/4) hal2-daemon::budgets the_daemon_answers_within_its_budgets\n"
        )
        self.assertEqual(scan.failing_tests(msg), [
            "everyPlaceAtOnceStaysResponsive", "servesThePage", "landings::tests::follows_landings_as_they_go",
            "hal2-daemon::budgets the_daemon_answers_within_its_budgets",
        ])
        self.assertEqual(scan.failed_task(msg), "libs.Hal2Kit test-unit")

    def test_a_test_named_by_nextest_and_cargo_counts_once(self):
        msg = ("    test a_terminal_agent_is_left_to_the_app ... FAILED\n"
               "  FAIL [  3.1s] (1/2) hal2-ffi::terminal_agents a_terminal_agent_is_left_to_the_app\n")
        self.assertEqual(scan.failing_tests(msg), ["hal2-ffi::terminal_agents a_terminal_agent_is_left_to_the_app"])

    def test_landing_start_from_its_id(self):
        self.assertAlmostEqual(
            scan.landing_start("2026-10-03T02-33-17.591Z-12"),
            scan.parse_time("2026-10-03T02:33:17.591Z"))
        self.assertIsNone(scan.landing_start(None))


class Findings(unittest.TestCase):
    def test_a_failed_landing_nobody_reruns_is_a_red_holder(self):
        q = [{"slot": "12", "state": "held", "enqueued": "2026-10-03T02:33:17Z", "process_alive": False,
              "hold": {"reason": "failed", "step": "worktree-pre-merge", "attempts": 7,
                       "message": "libs.Hal2Kit test-unit (x) failed\n✘ Test slow() failed after 1 s"}}]
        w = [{"slot": "12", "ahead": 2, "agent_state": "sleeping", "agent_idle_seconds": 9000}]
        kinds = [(f["kind"], f["slot"]) for f in scan.findings(snap(queue=q, worktrees=w))]
        self.assertEqual(kinds[0], ("red-holder", "12"))
        self.assertNotIn(("work-not-queued", "12"), kinds)

    def test_a_priority_slot_comes_first_with_its_place(self):
        q = [{"slot": "12", "state": "active", "process_alive": True}, {"slot": "04", "state": "waiting",
              "process_alive": True}]
        w = [{"slot": "04", "ahead": 25, "agent_state": "working"}]
        f = scan.findings(snap(queue=q, worktrees=w, priority={"slots": ["04"], "note": "n8n"}))
        self.assertEqual(f[0]["kind"], "priority")
        self.assertIn("#1 in the queue, waiting", f[0]["why"])

    def test_a_ci_landing_under_test_is_no_idle_reservation(self):
        q = [{"slot": "12", "state": "held", "enqueued": "2026-10-03T02:33:17Z", "process_alive": True,
              "hold": {"reason": "reserved"}}]
        w = [{"slot": "12", "ahead": 2, "agent_state": "idle", "agent_idle_seconds": 9000}]
        self.assertNotIn("reserved-idle", [f["kind"] for f in scan.findings(snap(queue=q, worktrees=w))])
        q[0]["process_alive"] = False
        self.assertIn("reserved-idle", [f["kind"] for f in scan.findings(snap(queue=q, worktrees=w))])

    def test_a_reserved_holder_that_works_is_no_idle_reservation(self):
        # hal2 plan 0169, 2026-10-06 21:37: 05 held the queue reserved between two dispatched landing runs of its
        # measurement; reserved-idle told it to land. Its turn had just ended, a shell waited, a run was unfinished.
        q = [{"slot": "05", "state": "held", "enqueued": "2026-10-03T02:33:17Z", "process_alive": False,
              "hold": {"reason": "reserved"}}]
        kinds = lambda w, **kw: [f["kind"] for f in scan.findings(snap(queue=q, worktrees=[w], **kw))]  # noqa: E731
        idle = {"slot": "05", "ahead": 2, "agent_state": "done", "agent_idle_seconds": 9000}
        self.assertIn("reserved-idle", kinds(idle))
        self.assertNotIn("reserved-idle", kinds(dict(idle, agent_idle_seconds=120)), "its turn just ended")
        self.assertNotIn("reserved-idle", kinds(dict(idle, agent_tasks=1)), "a background shell runs")
        self.assertNotIn("reserved-idle", kinds(idle, runs_unfinished=1), "a landing-workflow run is unfinished")
        self.assertNotIn("reserved-idle", kinds(dict(idle, agent_state="working", agent_idle_seconds=0)))

    def test_a_held_landing_whose_agent_works_is_left_alone(self):
        q = [{"slot": "12", "state": "held", "process_alive": False, "hold": {"reason": "failed"}}]
        w = [{"slot": "12", "ahead": 2, "agent_state": "working"}]
        self.assertEqual(scan.findings(snap(queue=q, worktrees=w)), [])

    def test_a_landing_paused_by_a_smuggle_and_the_smuggle_itself_are_no_stuck_holders(self):
        # hal2 plan 0228: the user's smuggle pauses the holder in place (`paused_by`), the holder resumes by itself;
        # a chained smuggle's verification taken over is a paused smuggle ticket. None is woken or released.
        held = {"slot": "12", "state": "held", "process_alive": False, "enqueued": "2026-10-03T02:33:17Z",
                "hold": {"reason": "failed", "step": "gate", "attempts": 3}}
        w = [{"slot": "12", "ahead": 2, "agent_state": "sleeping", "agent_idle_seconds": 9000},
             {"slot": "41", "ahead": 1, "agent_state": "working"}]
        kinds = lambda q: [f["kind"] for f in scan.findings(snap(queue=q, worktrees=w))]  # noqa: E731
        by = {"slot": "41", "seq": 7, "since": "2026-10-12T10:00:00Z"}
        smuggle = {"slot": "41", "state": "held", "process_alive": False, "hold": {"reason": "interrupted"},
                    "smuggle": {"phase": "verifying", "since": "2026-10-12T10:01:00Z", "run": 5}}
        self.assertIn("red-holder", kinds([held]))
        self.assertNotIn("red-holder", kinds([dict(held, paused_by=by), smuggle]))
        self.assertNotIn("held-idle", kinds([smuggle]), "the user's smuggle is never released")
        self.assertNotIn("held-idle", kinds([dict(smuggle, paused_by=by)]), "a verification taken over")
        waiter = {"slot": "41", "state": "waiting", "process_alive": False, "smuggle": {"phase": "queued"}}
        self.assertNotIn("waiter-gone", kinds([dict(held, process_alive=True), waiter]))

    def test_a_red_smuggle_or_land_run_is_a_red_holder_the_boss_wakes_and_never_releases(self):
        # Plan 0370 D1, D6: a failed smuggle (hold `failed`) or a CI landing reserved with a failed land run keeps
        # the queue; its own class, found for smuggle and landing alike, none while its session works.
        red = {"slot": "09", "state": "held", "process_alive": False, "enqueued": "2026-10-18T03:00:00Z", "seq": 4,
               "smuggle": {"phase": "checking"},
               "hold": {"reason": "failed", "step": "checks", "attempts": 2, "message": "rust-test failed"}}
        w = [{"slot": "09", "ahead": 2, "agent_state": "sleeping", "agent_idle_seconds": 9000}]
        got = [f for f in scan.findings(snap(queue=[red], worktrees=w)) if f["kind"] == "red-holder"]
        self.assertEqual([(f["slot"], f["what"], f["step"], f["attempts"]) for f in got], [("09", "smuggle", "checks", 2)])
        busy = [dict(w[0], agent_state="working")]
        self.assertEqual(scan.findings(snap(queue=[red], worktrees=busy)), [], "its session fixes it")
        land = {"slot": "09", "state": "held", "process_alive": False, "enqueued": "2026-10-18T03:00:00Z",
                "hold": {"reason": "reserved"}}
        runs = [{"slot": "09", "outcome": "failed", "task": "rust-test"}]
        got = [f for f in scan.findings(snap(queue=[land], worktrees=w, landings=runs)) if f["kind"] == "red-holder"]
        self.assertEqual([(f["what"], f["step"]) for f in got], [("landing", "rust-test")])
        ok = [{"slot": "09", "outcome": "running"}]
        self.assertEqual([f["kind"] for f in scan.findings(snap(queue=[land], worktrees=w, landings=ok))],
                         ["reserved-idle"], "a reservation without a failed run stays reserved-idle")

    def test_high_load_during_a_landing_names_the_busy_slots(self):
        q = [{"slot": "01", "state": "active", "process_alive": True, "active_seconds": 60}]
        w = [{"slot": "01", "ahead": 1, "agent_state": "working"},
             {"slot": "05", "ahead": 3, "agent_state": "working"}]
        f = scan.findings(snap(queue=q, worktrees=w, load={"load1": 90, "cores": 10, "per_core": 9}))
        self.assertEqual(f[0]["kind"], "load-high")
        self.assertEqual(f[0]["busy_slots"], ["05"])

    def test_finished_work_and_orphaned_work_are_found(self):
        w = [{"slot": "04", "ahead": 5, "agent_state": "done", "agent_idle_seconds": 3600, "plan": "0094"},
             {"slot": "11", "ahead": 13, "agent_state": None, "agent_idle_seconds": 0, "plan": "0085"},
             {"slot": "03", "ahead": 0, "agent_state": "sleeping", "agent_idle_seconds": 9999}]
        kinds = [(f["kind"], f["slot"]) for f in scan.findings(snap(worktrees=w))]
        self.assertEqual(kinds, [("work-not-queued", "04"), ("work-without-agent", "11")])

    def test_repeat_failures_are_flaky_candidates_and_long_queues_trains(self):
        tests = {"slow": {"test": "slow", "failures": 3, "slots": ["12"]},
                 "once": {"test": "once", "failures": 1, "slots": ["01"]}}
        q = [{"slot": s, "state": "waiting", "process_alive": True} for s in ("01", "02", "09")]
        kinds = [f["kind"] for f in scan.findings(snap(tests=tests, queue=q))]
        self.assertEqual(kinds, ["flaky-candidate", "long-queue"])

    def test_landings_summary_counts_tests_per_slot(self):
        now = time.time()
        landings = [
            {"id": "a", "worktree": "/x/12", "started": "2099-01-01T00:00:00Z", "outcome": "failed",
             "message": "t (x) failed\n✘ Test slow() failed after 1 s"},
            {"id": "b", "worktree": "/x/09", "started": "2099-01-01T00:00:00Z", "outcome": "failed",
             "message": "t (x) failed\n✘ Test slow() failed after 1 s"},
            {"id": "c", "worktree": "/x/01", "started": "2000-01-01T00:00:00Z", "outcome": "failed",
             "message": "✘ Test old() failed after 1 s"},
        ]
        recent, tests = scan.landings_summary(landings, now)
        self.assertEqual([r["id"] for r in recent], ["a", "b"])
        self.assertEqual(tests["slow"]["slots"], ["12", "09"])


class Summary(unittest.TestCase):
    def test_the_summary_names_queue_findings_actions_and_worktrees(self):
        q = [{"slot": "12", "state": "held", "hold": {"reason": "failed", "attempts": 7}}]
        f = [{"kind": "held-idle", "slot": "12", "why": "nobody reruns"}]
        w = [{"slot": "12", "ahead": 2, "agent_state": "sleeping", "plan": "0114-keys"},
             {"slot": "03", "ahead": 0, "agent_state": "idle", "plan": ""}]
        acts = [{"at": "2026-10-03T07:40:00", "kind": "wake", "slot": "12", "what": "told to rerun", "note": ""}]
        land = [{"slot": "01", "outcome": "landed", "task": "", "tests": []}]
        text = scan.render_summary(snap(queue=q, findings=f, worktrees=w), acts, land, "Unblocked 12.", "Answered 05.")
        for part in ("# farmer ", "## Development foreman", "Answered 05.", "Queue head: 12 held", "Unblocked 12.", "- 01 landed", "0. 12 held (failed, attempt 7)",
                     "- held-idle 12: nobody reruns", "- 07:40 wake 12: told to rerun", "| 12 | 2 | sleeping |"):
            self.assertIn(part, text)
        self.assertNotIn("| 03 |", text)

    def test_old_log_entries_without_note_or_slot_render(self):
        """Plan 0137: an entry without `note` crashed every tick at the summary."""
        acts = [{"at": "2026-10-04T21:00:00", "kind": "ask", "slot": "12", "what": "go?"},
                {"at": "2026-10-04T21:05:00", "kind": "lead", "what": "no slot", "note": None}]
        text = scan.render_summary(snap(findings=[]), acts, [], "")
        self.assertIn("- 21:00 ask 12: go?", text)
        self.assertIn("- 21:05 lead : no slot", text)

    def test_log_entries_are_read_tolerantly_and_written_whole(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "log.jsonl"
            f.write_text('{"at": "2026-10-04T21:00:00", "kind": "ask"}\nnot json\n{"kind": "no at"}\n')
            self.assertEqual(scan.entries(f), [{"at": "2026-10-04T21:00:00", "kind": "ask", "slot": "", "what": "",
                                                "note": ""}])
            old, scan.DATA = scan.DATA, Path(d)
            try:
                main = str(Path(d) / "hal2")
                scan.state_dir(main).mkdir(parents=True, exist_ok=True)
                scan.log(main, {"kind": "decision", "slot": "12"})
                self.assertEqual(scan.entries(scan.state_dir(main) / "log.jsonl")[0]["note"], "")
            finally:
                scan.DATA = old

    def test_the_summaries_live_in_the_state_folder(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            old, scan.DATA = scan.DATA, Path(d) / "state"
            try:  # the summaries live in the state folder, ignored with the rest of roles/farmer/
                self.assertEqual(scan.summary_dir(str(Path(d) / "hal2")), Path(d) / "state/hal2/summaries")
                self.assertTrue(scan.summary_dir(str(Path(d) / "hal2")).is_dir())
            finally:
                scan.DATA = old


LEAD = {"slot": "02", "plan": "0149-hal9k", "step": "7"}


class Subservants(unittest.TestCase):
    """Skills plan 0013: a worktree with plans/LEAD is a parallel plan's servant and never lands."""

    def test_the_marker_is_read_a_missing_one_is_none_a_broken_one_bad_but_marked(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(scan.lead_of(d))
            (Path(d) / "plans").mkdir()
            (Path(d) / "plans/LEAD").write_text("02 0149-hal9k\n")  # review 1 finding 10: still marked
            bad = scan.lead_of(d)
            self.assertTrue(bad["bad"])
            self.assertIn("servant with a broken marker (plans/LEAD is not", scan.subservant(bad))
            (Path(d) / "plans/LEAD").write_text("02 0149-hal9k 7\n")
            self.assertEqual(scan.lead_of(d), LEAD)

    def test_a_broken_marker_counts_as_marked_in_the_findings(self):
        bad = {"bad": True, "text": "x", "error": "plans/LEAD is not `<lead-slot> <plan> <step>`: 'x'"}
        q = [{"slot": "31", "state": "waiting", "seq": 5, "process_alive": False}]
        w = [{"slot": "31", "ahead": 5, "agent_state": "done", "agent_idle_seconds": 3600, "plan": "x", "lead": bad,
              "missing": [bad["error"], "HEAD: 5 commit(s) not in origin/main"]}]
        f = scan.findings(snap(queue=q, worktrees=w))
        self.assertEqual([x["kind"] for x in f], ["subservant-holds"])
        self.assertIn("broken marker", f[0]["why"])
        orphan = scan.findings(snap(worktrees=[dict(w[0], agent_state=None)]))
        self.assertEqual([x["kind"] for x in orphan], ["work-without-agent"])
        self.assertIn("broken marker", orphan[0]["why"])

    def test_every_worktree_of_the_snapshot_carries_its_lead(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "31/plans").mkdir(parents=True)
            (Path(d) / "31/plans/LEAD").write_text("02 0149-hal9k 7\n")
            (Path(d) / "04").mkdir()
            wts = [{"path": str(Path(d) / s), "branch": s} for s in ("31", "04")]
            with mock.patch.object(scan, "run", return_value=""), \
                    mock.patch.object(scan, "run_json", return_value=None), \
                    mock.patch.object(scan, "worktrees", return_value=wts), \
                    mock.patch.object(scan, "unmerged", return_value=3), \
                    mock.patch.object(scan.mtm_ci, "ci_mode", return_value=False), \
                    mock.patch.object(scan, "state_dir", return_value=Path(d) / "state"):
                got = scan.snapshot(d, 24, fetch=False)
        self.assertEqual({w["slot"]: w["lead"] for w in got["worktrees"]}, {"31": LEAD, "04": None})

    def test_a_marked_slot_with_finished_work_is_not_told_to_queue(self):
        w = [{"slot": "31", "ahead": 5, "agent_state": "done", "agent_idle_seconds": 3600, "plan": "x", "lead": LEAD},
             {"slot": "04", "ahead": 5, "agent_state": "done", "agent_idle_seconds": 3600, "plan": "y", "lead": None}]
        self.assertEqual([(f["kind"], f["slot"]) for f in scan.findings(snap(worktrees=w))],
                         [("work-not-queued", "04")])

    def test_a_marked_orphan_names_its_lead(self):
        w = [{"slot": "31", "ahead": 2, "agent_state": None, "agent_idle_seconds": 0, "plan": "x", "lead": LEAD,
              "missing": ["HEAD: 2 commit(s) not in origin/02"]}]
        f = scan.findings(snap(worktrees=w))
        self.assertEqual([(x["kind"], x["slot"], x["lead"]) for x in f], [("work-without-agent", "31", LEAD)])
        self.assertIn("servant of field 02's plan 0149-hal9k (step 7): HEAD: 2 commit(s) not in origin/02", f[0]["why"])
        merged = [dict(w[0], missing=[])]  # review 1 finding 3: ahead of main, but all of it in origin/02
        self.assertEqual(scan.findings(snap(worktrees=merged)), [])

    def test_a_marked_slot_holding_or_waiting_in_the_queue_is_subservant_holds_only(self):
        q = [{"slot": "31", "state": "held", "seq": 4, "process_alive": False, "enqueued": iso(3600),
              "hold": {"reason": "failed", "message": "x failed"}},
             {"slot": "32", "state": "waiting", "seq": 5, "process_alive": False}]
        w = [{"slot": s, "ahead": 2, "agent_state": "idle", "agent_idle_seconds": 9000, "lead": LEAD}
             for s in ("31", "32")]
        f = scan.findings(snap(queue=q, worktrees=w))
        self.assertEqual([(x["kind"], x["slot"]) for x in f], [("subservant-holds", "31"), ("subservant-holds", "32")])
        self.assertEqual(f[0]["lead"], LEAD)
        unmarked = [dict(x, lead=None) for x in w]
        self.assertEqual([x["kind"] for x in scan.findings(snap(queue=q, worktrees=unmarked))],
                         ["red-holder", "waiter-gone"])


def iso(seconds_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


class Reservations(unittest.TestCase):
    HEAD = {"slot": "18", "state": "waiting", "seq": 9, "process_alive": False, "awaiting_slot": True}

    def kinds(self, reserved_ago: float, **agent):
        q = [dict(self.HEAD, reserved={"by": "the user", "since": iso(reserved_ago)})]
        w = [{"slot": "18", "ahead": 3, **agent}]
        return [(f["kind"], f["slot"]) for f in scan.findings(snap(queue=q, worktrees=w))]

    def test_a_reservation_waiting_an_hour_at_the_front_without_progress_is_found(self):
        self.assertIn(("reservation-waits", "18"), self.kinds(2 * 3600))
        self.assertIn(("reservation-waits", "18"), self.kinds(2 * 3600, agent_state="done",
                                                                agent_idle_seconds=4000))

    def test_a_young_reservation_or_a_working_slot_is_left_alone(self):
        self.assertNotIn(("reservation-waits", "18"), self.kinds(600))
        self.assertNotIn(("reservation-waits", "18"), self.kinds(2 * 3600, agent_state="working"))
        self.assertNotIn(("reservation-waits", "18"), self.kinds(2 * 3600, agent_state="done",
                                                                   agent_idle_seconds=300))

    def test_a_reserved_waiter_without_a_process_is_not_gone(self):
        q = [{"slot": "12", "state": "active", "process_alive": True},
             dict(self.HEAD, reserved={"by": "the user", "since": iso(60)})]
        kinds = [f["kind"] for f in scan.findings(snap(queue=q))]
        self.assertNotIn("waiter-gone", kinds)


class Priority(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        old, scan.DATA = scan.DATA, Path(self.tmp.name)
        self.addCleanup(setattr, scan, "DATA", old)
        self.file = scan.state_dir("/x/hal2") / "priority.json"

    def order(self, *args, stdout="", code=0, **kw):
        import subprocess
        from unittest import mock
        real, hal2 = subprocess.run, []

        def run(argv, **opts):  # only hal2 is faked: roles' git calls stay real
            if argv[0] != "hal2-cli-git":
                return real(argv, **opts)
            hal2.append(argv)
            return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr="refused" if code else "")
        with mock.patch.object(scan.subprocess, "run", side_effect=run), \
                mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            rc = scan.priority("/x/hal2", list(args), **kw)
        return rc, hal2[0] if hal2 else None

    def test_hal2_orders_the_queue_and_its_resolved_order_is_kept_with_the_note(self):
        import json
        out = json.dumps({"queue": [], "priority": {"slots": ["12", "18"], "by": "the user", "at": "A"}})
        rc, argv = self.order("12", "18", stdout=out, note="n8n first")
        self.assertEqual((rc, argv), (0, ["hal2-cli-git", "worktree", "queue", "order", "12", "18",
                                          "--by", "hal2/farmer-hal2", "--json"]))
        self.assertEqual(json.loads(self.file.read_text()), {"slots": ["12", "18"], "note": "n8n first"})
        self.assertEqual(self.order(done="12")[1], None, "--done asks hal2 nothing")
        self.assertEqual(json.loads(self.file.read_text())["slots"], ["18"])
        self.order(done="18")
        self.assertFalse(self.file.exists(), "the last landed slot clears it")

    def test_an_installed_cli_without_by_is_retried_once_without_it_and_says_so(self):
        import io
        import json
        import subprocess
        from unittest import mock
        real, hal2 = subprocess.run, []
        ok = json.dumps({"queue": [], "priority": {"slots": ["12"], "by": "the user (hal2-cli-git)", "at": "A"}})

        def run(argv, **opts):
            if argv[0] != "hal2-cli-git":
                return real(argv, **opts)
            hal2.append(argv)
            if "--by" in argv:
                return subprocess.CompletedProcess(argv, 2, stdout="", stderr='unknown argument "--by" for worktree queue order')
            return subprocess.CompletedProcess(argv, 0, stdout=ok, stderr="")
        err = io.StringIO()
        with mock.patch.object(scan.subprocess, "run", side_effect=run), mock.patch("sys.stdout"), \
                mock.patch("sys.stderr", err):
            rc = scan.priority("/x/hal2", ["12"])
        self.assertEqual(rc, 0)
        self.assertEqual([("--by" in a) for a in hal2], [True, False], "retried once, without --by")
        self.assertEqual(hal2[1], ["hal2-cli-git", "worktree", "queue", "order", "12", "--json"])
        self.assertIn("does not know --by", err.getvalue())

    def test_clear_and_a_refusal(self):
        import json
        self.file.write_text(json.dumps({"slots": ["04"], "note": ""}))
        rc, _ = self.order("99", code=1)
        self.assertEqual(rc, 1)
        self.assertTrue(self.file.exists(), "a refused order changes nothing")
        rc, argv = self.order(clear=True, stdout=json.dumps({"queue": [], "priority": None}))
        self.assertEqual((rc, argv[-4:]), (0, ["--clear", "--by", "hal2/farmer-hal2", "--json"]))
        self.assertFalse(self.file.exists())

    def test_the_order_names_its_setter_the_roles_field_or_the_user(self):
        """Hal2 plan 0313 step 12 (D18): `queue order` runs in the main checkout, so the caller passes `--by`."""
        import json
        out = json.dumps({"queue": [], "priority": {"slots": ["12"], "by": "x", "at": "A"}})

        def by(role="farmer", **kw):
            argv = self.order("12", stdout=out, role=role, **kw)[1]
            return argv[argv.index("--by") + 1], argv[-1]
        self.assertEqual(by(), ("hal2/farmer-hal2", "--json"))
        self.assertEqual(by(role="tollman"), ("hal2/tollman-hal2", "--json"))
        self.assertEqual(by(by="user"), ("user", "--json"), "the farmer relaying the user's words")
        self.assertEqual(scan.setter("/x/hal2", "tollman"), "hal2/tollman-hal2")


class Roles(unittest.TestCase):
    """Hal2 plan 0294 step 5: the scan serves the tollman's boss too. A hitched ticket (`worktree queue ready`,
    no process by design) is no gone waiter, a role's field is no worktree with work to land, and the command line
    writes the folder of the role it is told."""

    READY = {"at": "2026-10-13T10:00:00Z", "head": "a" * 40, "by": "hal2/07"}

    def scan(self, d, queue, wts):
        from pathlib import Path
        from unittest import mock
        def answers(args, cwd=None):  # no session runs (an empty list, read: plan 0412 tells it from an unreadable one)
            if args[:3] == ["hal2-cli-git", "worktree", "queue"]:
                return {"queue": queue}
            return {"agents": []} if args == ["hal2-cli-agents", "list", "--json"] else None
        with mock.patch.object(scan, "run", return_value=""), mock.patch.object(scan, "run_json", answers), \
                mock.patch.object(scan, "worktrees", return_value=wts), \
                mock.patch.object(scan, "unmerged", return_value=3), \
                mock.patch.object(scan.mtm_ci, "ci_mode", return_value=False), \
                mock.patch.object(scan, "state_dir", return_value=Path(d) / "state"):
            return scan.snapshot(d, 24, fetch=False)

    def test_a_hitched_ticket_is_not_a_gone_waiter(self):
        import tempfile
        q = [{"slot": "12", "state": "active", "pid": 0}, {"slot": "07", "state": "waiting", "pid": 0},
             {"slot": "09", "state": "waiting", "pid": 0, "ready": self.READY}]
        with tempfile.TemporaryDirectory() as d:
            got = self.scan(d, q, [])
        self.assertEqual([t["ready"] for t in got["queue"]], [None, None, self.READY])
        self.assertEqual([(f["kind"], f["slot"]) for f in got["findings"] if f["kind"] == "waiter-gone"],
                         [("waiter-gone", "07")])

    def test_a_standing_train_and_the_hitched_are_no_waiters_and_a_role_s_hold_is_its_own(self):
        # Hal2 plan 0294 step 6: the tollman's field carries every train; its ticket and the cars' have no
        # process by design, and its red train's hold is the train engine's to move, never released by the boss.
        import tempfile
        train = {"carrier": "tollman-hal2", "cars": [{"field": "07"}, {"field": "09"}, {"field": "11"}]}
        q = [{"slot": "tollman-hal2", "state": "waiting", "pid": 0, "train": train}]
        q += [{"slot": s, "state": "waiting", "pid": 0, "ready": self.READY} for s in ("07", "09", "11")]
        with tempfile.TemporaryDirectory() as d:
            got = self.scan(d, q, [])
            self.assertEqual((got["queue"][0]["train"], got["queue"][1]["train"]), (train, None))
            self.assertEqual(got["findings"], [], "no waiter-gone, no long-queue")
            q[0].update(state="held", train=None, hold={"reason": "failed", "step": "gate", "attempts": 1})
            self.assertEqual(self.scan(d, q, [])["findings"], [])
            q[0]["slot"] = "12"
            self.assertEqual([f["kind"] for f in self.scan(d, q, [])["findings"]], ["red-holder"])

    def test_a_leaving_ticket_is_nobody_s_to_wake_or_release_and_no_waiter(self):
        # Hal2 plan 0263 D129 (in the barn since e754fa577): a head's ticket that ended stays held, `waits_for` says
        # for which run of its worktree, and goes by itself. Its hold reads like a reservation or the failure it had.
        import tempfile
        why = "run 9 of hal2/12 is still queued or in progress"
        left = {"slot": "12", "state": "held", "pid": 0, "enqueued": "2026-10-03T02:33:17Z", "waits_for": why,
                "hold": {"reason": "reserved", "message": "ended; held until its worktree's runs have ended"}}
        q = [left] + [{"slot": s, "state": "waiting", "pid": 0, "ready": self.READY} for s in ("07", "09", "11")]
        wts = [{"path": "/x/12", "branch": "12"}]
        with tempfile.TemporaryDirectory() as d:
            got = self.scan(d, q, wts)
            self.assertEqual([t["waits_for"] for t in got["queue"]], [why, None, None, None])
            self.assertEqual(got["findings"], [], "no reserved-idle, no waiter-gone, no long-queue")
            left["hold"] = {"reason": "failed", "step": "gate", "attempts": 2}
            self.assertNotIn("held-idle", [f["kind"] for f in self.scan(d, q, wts)["findings"]])
            self.assertIn("0. 12 held (leaving: run 9 of hal2/12 is still queued or in progress)",
                          scan.render_summary(got, [], [], ""))
            for hold, kind in (({"reason": "reserved"}, "reserved-idle"), (left["hold"], "red-holder")):
                held = [dict(left, hold=hold, waits_for=None)] + q[1:]
                self.assertIn(kind, [f["kind"] for f in self.scan(d, held, wts)["findings"]], "the same ticket, held")

    def test_a_role_s_field_is_left_out_of_the_worktrees(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            names = ("04", "farmer-hal2", "tollman-hal2", "farmer")
            for n in names:
                (Path(d) / n).mkdir()
            got = self.scan(d, [], [{"path": str(Path(d) / n), "branch": n} for n in names])
        self.assertEqual([w["slot"] for w in got["worktrees"]], ["04"])
        self.assertEqual([f["slot"] for f in got["findings"]], ["04"], "only the numbered field has work to land")

    def test_a_nested_hand_worktree_is_no_field_and_no_orphan(self):
        """Wagon engine fix (plan 0313 step 2): the Agent tool's `<field>/.claude/worktrees/agent-x` is listed by git
        but has no session of its own; the 09:04 UTC round woke sessions for such paths."""
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            main, field = str(Path(d) / "hal2"), Path(d) / "04"
            nested = field / ".claude" / "worktrees" / "agent-x"
            lone = Path(d) / "other" / ".claude" / "worktrees" / "agent-y"  # its field is no worktree: still listed
            porcelain = "".join(f"worktree {p}\nHEAD {'a' * 40}\nbranch refs/heads/{b}\n\n"
                                for p, b in ((main, "main"), (field, "04"), (nested, "worktree-agent-x"), (lone, "y")))
            fake = lambda args, cwd=None: porcelain if args[:3] == ["git", "worktree", "list"] else ""
            for p in (field, nested, lone):
                p.mkdir(parents=True)
            no_agents = lambda args, cwd=None: {"agents": []} if args[:2] == ["hal2-cli-agents", "list"] else None
            with mock.patch.object(scan, "run", fake), mock.patch.object(scan, "run_json", no_agents), \
                    mock.patch.object(scan, "unmerged", return_value=3), \
                    mock.patch.object(scan.mtm_ci, "ci_mode", return_value=False), \
                    mock.patch.object(scan, "state_dir", return_value=Path(d) / "state"):
                listed = [w["path"] for w in scan.worktrees(main)]
                got = scan.snapshot(main, 24, fetch=False)
        self.assertEqual(listed, [str(field), str(lone)])
        slots = [w["slot"] for w in got["worktrees"]]
        self.assertNotIn("agent-x", slots + [f["slot"] for f in got["findings"]])
        self.assertIn("04", [f["slot"] for f in got["findings"]], "the field itself is still judged")

    def test_the_command_line_writes_the_folder_of_the_role_it_is_told(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.object(scan, "DATA", Path(d) / "state"), \
                mock.patch.object(scan.shutil, "which", return_value="/bin/x"), mock.patch("sys.stdout"):
            repo, wm = str(Path(d) / "hal2"), scan.state_dir(str(Path(d) / "hal2"), "tollman")
            Path(repo).mkdir()
            farmers = scan.state_dir(repo)
            (wm / "priority.json").write_text(json.dumps({"slots": ["07", "09"], "note": "n"}))
            for argv in (["pause", "--note", "ci is down"], ["record", "train", "07", "formed"],
                         ["priority", "--done", "07"]):
                self.assertEqual(scan.main([*argv, "--repo", repo, "--role", "tollman"]), 0, argv)
            self.assertEqual(json.loads((wm / "paused.json").read_text())["note"], "ci is down")
            self.assertEqual(json.loads((wm / "priority.json").read_text())["slots"], ["09"])
            self.assertEqual([e["kind"] for e in scan.entries(wm / "log.jsonl")], ["pause", "train", "priority"])
            self.assertEqual(sorted(f.name for f in farmers.iterdir()), ["tollman"], "nothing of the farmer's")
            self.assertEqual(scan.main(["record", "lead", "07", "told", "--repo", repo]), 0)
            self.assertEqual([e["kind"] for e in scan.entries(farmers / "log.jsonl")], ["lead"], "the default")


class SubservantWork(worktree_farm.MarkedSlots):
    """Review 1 finding 3: a marked worktree's work is measured against origin/<foreman>, never main, so a servant whose
    step its foreman merged is not restarted with /handoff c every 3 hours. 31: merged into origin/02; 32: not."""

    def entry(self, name):
        return scan.worktree_entry({"path": str(self.base / name), "branch": name}, {}, "main", time.time())

    def test_a_subservant_merged_into_its_leads_branch_has_nothing_missing(self):
        merged, unmerged = self.entry("31"), self.entry("32")
        self.assertEqual(merged["ahead"], 2, "its commits are not on main ...")
        self.assertEqual(merged["missing"], [], "... but all of them are in origin/02")
        self.assertEqual(unmerged["missing"], ["HEAD: 1 commit(s) not in origin/02",
                                               "origin/32: 1 commit(s) not in origin/02"])
        self.assertNotIn("missing", self.entry("13"), "an unmarked slot is unchanged")
        got = scan.findings(snap(worktrees=[merged, unmerged]))
        self.assertEqual([(f["kind"], f["slot"]) for f in got], [("work-without-agent", "32")])

    def test_the_leads_branch_is_fetched_before_it_is_measured(self):
        test_farmer.git(self.main, "update-ref", "refs/remotes/origin/02", "origin/main")  # a stale origin/02
        self.assertIn("HEAD: 2 commit(s) not in origin/02", self.entry("31")["missing"])
        scan.fetch_leads(str(self.main), [str(self.base / s) for s in ("31", "13")])
        self.assertEqual(self.entry("31")["missing"], [])


if __name__ == "__main__":
    unittest.main()
