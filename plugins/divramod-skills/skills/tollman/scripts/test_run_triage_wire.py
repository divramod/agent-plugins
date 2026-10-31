"""Hal2 plan 0490 step 3: the finished land run's triage, wired into the watch (run_triage_wire.py; D6, D9, D13).

- the next train first: a pass that tells the merge job green and the workflow finished together carries out the
  chain that forms the next train, while the triage only marks its run due and spawns a detached child, reading
  nothing (no gh, no git) in the pass; the child waits for the tick lock, so it reads only after that pass
- train 27's recorded run through the wired path: no order to its cars 02, 09, 21 (L131); the pipeline reds go to
  the ROLE.md's `pipeline_field`; the run's signatures are kept and fed to the next run (`kept`, no gh call)
- a budget miss twice (L13): the flaky brief through the wired path; a failed or stuck child: one wake
- post_merge after the merge leaves a red the triage places to it (D13); a plain car red is ordered as before
"""
# enforces .adr/deterministic-first.md and .adr/tollman.md

import datetime as dt
import fcntl
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import chain
import ci_health
import minute
import mtm_scan
import post_merge
import role_cli
import run_triage_gather
import run_triage_read as read
import run_triage_wire as wire
import test_run_triage as T
import watch_events
from test_triage_kinds_l13_l64 import BUDGET_LOG, STACK

URL = "https://github.com/divramod/hal2/actions/runs/41009203691"
RID = "41009203691"
NOW = dt.datetime(2026, 10, 30, 6, 0, tzinfo=dt.timezone.utc)
FINISHED = {"key": f"done:{RID}", "kind": "finished", "text": f"workflow finished: failure ({URL})"}
MERGED = {"key": f"merge:{RID}", "kind": "merge-green", "text": f"merge job green: d2-01-git-merge ({URL})"}
WATCHED = {"run": RID, "url": URL, "train": "train-27", "started": "2026-10-30T05:34:00Z"}


class Folder(unittest.TestCase):
    """A field `top` and a main checkout whose tollman state folder is a temp dir; no gh, no queue."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.top, self.main, self.state = Path(tmp.name, "tollman-hal2"), Path(tmp.name, "hal2"), Path(tmp.name, "st")
        for d in (self.top, self.main, self.state):
            d.mkdir()
        self.spawned = []
        for p in (mock.patch.object(mtm_scan, "state_dir", lambda main, role=None: self.state),  # never the user's
                  mock.patch.object(mtm_scan, "main_checkout", lambda top: str(self.main)),
                  mock.patch.object(mtm_scan, "run_json", lambda args, cwd=None: {"queue": []}),
                  mock.patch.object(wire, "SPAWN", lambda argv, **kw: self.spawned.append((argv, kw)))):
            p.start()
            self.addCleanup(p.stop)

    def gather(self, n="27", seen=None):
        """A fake run_triage_gather.gather answering train `n`'s recorded run, its `previous` from the `kept`
        signatures handed in (as the real one does), with every call noted in `seen`."""
        def fake(main, train, url, panes, pipeline_field=None, dedup=None, kept=None, **kw):
            data, jobs, log = T.recorded(n)
            (seen if seen is not None else []).append(sorted(kept or {}))
            run = {"id": url.rsplit("/", 1)[-1], "url": url, "sha": data["headSha"], "base": T.TRAINS[n]["base"],
                   "at": data["createdAt"]}
            previous = [{"id": k, "units": v} for k, v in reversed(list((kept or {}).items()))]
            return run, jobs, log, T.context(n, previous=previous, live=set(panes), pipeline_field=pipeline_field,
                                             dedup={**(dedup or {}), "plans": {}})
        return fake

    def keep26(self):
        _, jobs, log = T.recorded("26")
        wire.update(str(self.main), "40971471569", lambda e: e.update(at="2026-10-29T23:59:00+00:00",
                                                                     units=read.signatures(jobs, log)))

    def triage(self, url=URL, gather=None, panes=None, wait=lambda top: None):
        return wire.run(str(self.top), url, "train-27", {"panes": panes or {}, "log": []}, NOW, wait,
                        gather=gather or self.gather())


class NextTrainFirst(Folder):
    def events(self, fresh):
        formed = chain.action(str(self.top), f"merge-green:{WATCHED['train']}")
        with mock.patch.object(watch_events, "new", lambda main, rows, dry: list(fresh)), \
                mock.patch.object(watch_events, "state", lambda main: dict(WATCHED)), \
                mock.patch.object(minute, "early", lambda *a, **kw: []), \
                mock.patch.object(minute, "next_train", lambda *a, **kw: [formed]), \
                mock.patch.object(ci_health, "check", lambda *a, **kw: []), \
                mock.patch.object(minute.train_state, "lines", lambda main: []), \
                mock.patch.object(run_triage_gather, "gather", side_effect=AssertionError("a read in the pass")):
            return minute.events(str(self.top), str(self.main), False, {"queue": []})

    def test_the_chain_comes_first_and_the_pass_reads_nothing_for_the_triage(self):
        planned = self.events([MERGED, FINISHED])
        kinds = [a["kind"] for a in planned]
        self.assertLess(kinds.index("chain"), kinds.index("run-triage"), "the next train forms first (D6)")
        self.assertEqual(planned[kinds.index("run-triage")]["do"], "record", "the pass only records the start")
        ((argv, kw),) = self.spawned
        self.assertEqual((Path(argv[1]).name, argv[2], argv[argv.index("--run") + 1]), ("run_triage_wire.py", "run", URL))
        self.assertTrue(kw["start_new_session"], "detached: the pass never waits for it")
        again = self.events([FINISHED])
        self.assertEqual(([a["kind"] for a in again if a["kind"] == "run-triage"], len(self.spawned)), ([], 1),
                         "once per run: a marked run is never spawned again")

    def test_a_dry_round_plans_the_start_and_spawns_nothing(self):
        with mock.patch.object(watch_events, "new", lambda main, rows, dry: [FINISHED]), \
                mock.patch.object(watch_events, "state", lambda main: dict(WATCHED)):
            got = minute.triage(str(self.top), str(self.main), [FINISHED], True, {"queue": []})
        self.assertEqual(([a["key"] for a in got], self.spawned), ([f"run-triage:{RID}"], []))
        self.assertEqual(wire.state(str(self.main))["runs"], [])

    def test_the_child_reads_only_after_the_pass_that_started_it(self):
        order = []
        wire.run(str(self.top), URL, "train-27", {"panes": {}, "log": []}, NOW, lambda top: order.append("lock"),
                 gather=lambda *a, **kw: order.append("gather"))
        self.assertEqual(order, ["lock", "gather"], "the tick lock first: the pass's chain has run")
        taken = []
        with mock.patch.object(role_cli, "state", lambda repo, wiring: self.state), \
                mock.patch.object(fcntl, "flock", lambda f, op: taken.append((Path(f.name).name, op))):
            wire.after_the_round(str(self.top))
        self.assertEqual(taken, [("tick.lock", fcntl.LOCK_EX)], "the pass's and the round's own lock, blocking")


class Train27(Folder):
    def test_no_order_goes_to_its_cars(self):
        self.keep26()
        entry = self.triage(panes={"02": "%2", "09": "%9", "21": "%21", "27": "%27"})
        self.assertIsNone(entry["error"])
        cars = {"02", "09", "21"}
        self.assertFalse([a for a in entry["actions"] if a["slot"] in cars or cars & set(a.get("argv") or [])])
        self.assertIn(f"triage-wake:{RID}", [a["key"] for a in entry["actions"]], "the pipeline reds: unsure")

    def test_the_pipeline_field_of_the_role_file_gets_the_pipeline_reds(self):
        (self.top / "roles/tollman").mkdir(parents=True)
        (self.top / "roles/tollman/ROLE.md").write_text('---\nnotify: every-round\npipeline_field: "27"\n---\n')
        self.keep26()
        entry = self.triage(panes={"27": "%27"})
        (order,) = [a for a in entry["actions"] if a["kind"] == "triage-order"]
        self.assertEqual((order["slot"], order["do"], order["key"]), ("27", "send", f"triage:{RID}:stack-test"))

    def test_signatures_are_kept_and_fed_to_the_next_run(self):
        seen = []
        self.keep26()
        self.triage(gather=self.gather(seen=seen))
        self.triage(url=URL.replace(RID, "41100000000"), gather=self.gather(seen=seen))
        self.assertEqual(seen, [["40971471569"], ["40971471569", RID]])
        kept = {r["run"]: r for r in wire.state(str(self.main))["runs"]}
        self.assertIn("stack-test/hub-e2e", kept[RID]["units"])

    def test_the_planned_actions_run_in_the_next_pass_once_each(self):
        self.keep26()
        entry = self.triage()
        self.assertEqual(wire.pending(str(self.main), NOW + dt.timedelta(minutes=1)), entry["actions"])
        self.assertEqual(wire.pending(str(self.main), NOW + dt.timedelta(hours=wire.PENDING + 1)), [])


class Failures(Folder):
    def test_a_failed_child_is_one_wake(self):
        entry = self.triage(gather=mock.Mock(side_effect=RuntimeError("gh down")))
        self.assertEqual(entry["error"], "RuntimeError: gh down")
        (w,) = wire.pending(str(self.main), NOW)
        self.assertEqual((w["do"], w["key"]), ("wake", f"triage-failed:{RID}"))

    def test_a_child_that_never_wrote_is_one_wake_after_stuck_minutes(self):
        wire.due(str(self.main), URL, "train-27", now=NOW)
        wire.spawn(str(self.top), str(self.main), NOW)
        self.assertEqual(wire.pending(str(self.main), NOW + dt.timedelta(minutes=wire.STUCK - 1)), [])
        (w,) = wire.pending(str(self.main), NOW + dt.timedelta(minutes=wire.STUCK + 1))
        self.assertIn("no result", w["text"])

    def test_the_state_keeps_the_last_runs_only(self):
        for n in range(wire.KEEP + 3):
            wire.due(str(self.main), f"https://x/actions/runs/{n}", "t")
        self.assertEqual([r["run"] for r in wire.state(str(self.main))["runs"]],
                         [str(n) for n in range(3, wire.KEEP + 3)])


class BudgetTwice(Folder):
    """L13 (row 10): a latency-budget miss is a flake; the second time, the flaky brief, through the wired path."""

    def gather_budget(self, main, train, url, panes, pipeline_field=None, dedup=None, kept=None, **kw):
        rid = url.rsplit("/", 1)[-1]
        previous = [{"id": k, "units": v} for k, v in reversed(list((kept or {}).items()))]
        return ({"id": rid, "url": url, "sha": "a" * 40}, [STACK], BUDGET_LOG,
                {"previous": previous, "dedup": {"plans": {}}})

    def test_the_second_miss_sends_the_flaky_brief(self):
        first = self.triage(url="https://x/actions/runs/40", gather=self.gather_budget)
        self.assertEqual([a["kind"] for a in first["actions"]], ["triage-record"])
        second = self.triage(url="https://x/actions/runs/41", gather=self.gather_budget)
        self.assertEqual([a["kind"] for a in second["actions"]], ["triage-record", "triage-flaky"])


class Lanes(unittest.TestCase):
    """Row 7's lane helpers (L83, L87): of several cars that changed the pipeline, the one that moved the red job's
    lane is its owner, and the recheck recomputes the same from the evidence."""

    def test_the_car_that_moved_the_red_job_s_lane_owns_its_pipeline_red(self):
        import run_triage
        import run_triage_check as check
        cars = [{"field": "07", "files": [".github/workflows/merge-to-main-cloud.yml"]},
                {"field": "09", "files": ["code/bash/scripts/gate/jobs/hub-e2e.sh"]}]
        moved = {"07": [{"workflow": "w", "job": "e4", "from": [], "to": ["self-hosted"]}]}
        self.assertEqual(run_triage.pipeline_owner({"cars": cars, "moved": moved}, "e4-01-hub-deploy")["field"], "07")
        self.assertIsNone(run_triage.pipeline_owner({"cars": cars, "moved": moved}, "d1-01-stack-test")["field"])
        e = {"pipeline": run_triage.pipeline_owner({"cars": cars, "moved": moved}, "e4-01-hub-deploy")}
        self.assertEqual(check.pipeline(e), "07")


class PostMerge(Folder):
    """D13: after the merge job, post_merge orders nobody for a red the finished run's triage places."""

    def test_train_27_s_reds_are_left_to_the_triage(self):
        _, jobs, log = T.recorded("27")
        self.assertIn("stack-test/hub-e2e: a build-phase timeout, the pipeline's",
                      post_merge.the_triages(str(self.main), RID, jobs, log))

    def test_a_repeat_of_a_kept_run_is_left_to_the_triage(self):
        log = "\n".join(f"d1-01-rust-test\ttest\t{t}" for t in ("error: assertion failed at code/x/twenty.py:3",))
        jobs = [{"name": "d1-01-rust-test", "status": "completed", "conclusion": "failure",
                 "steps": [{"name": "test", "conclusion": "failure"}]}]
        self.assertIsNone(post_merge.the_triages(str(self.main), "2", jobs, log), "a car's red: ordered as before")
        wire.update(str(self.main), "1", lambda e: e.update(at=NOW.isoformat(), units=read.signatures(jobs, log)))
        self.assertIn("a repeat of run 1", post_merge.the_triages(str(self.main), "2", jobs, log))


if __name__ == "__main__":
    unittest.main()
