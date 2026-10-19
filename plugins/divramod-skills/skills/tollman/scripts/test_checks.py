"""Hal2 plan 0306 step 2: the duty `checks` (landings first on the runners, D4, D5) over fakes: the store in a
temporary folder, the queue, the train and gh as data or fake callables. Nothing reaches gh, a queue or a session."""

import contextlib
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import checks
import checks_cli
import checks_tell
import mtm_scan
import tick
import tollman

NOW = dt.datetime(2026, 10, 14, 10, 0, tzinfo=dt.timezone.utc)
ARGV = ["gh", "workflow", "run", "merge-to-main.yml", "--ref", "13", "-f", "title=[13] ci-check 0306 1/6"]
ROUTE = {"name": "00-x-host-x/route", "status": "completed", "conclusion": "success"}
CHANGES = {"name": "01-hz01-host-x/changes", "status": "in_progress", "conclusion": None}
LANE = {"name": "02-a-host-x/rust-test", "status": "in_progress", "conclusion": None}
SKIPPED = {"name": "02-a-host-x/rust-test", "status": "completed", "conclusion": "skipped"}


def check_run(rid, title="[13] ci-check 0306 1/6", status="queued"):
    return {"databaseId": rid, "event": "workflow_dispatch", "status": status, "headBranch": "13",
            "displayTitle": title, "url": f"https://x/runs/{rid}", "createdAt": "2026-10-14T10:00:00Z"}


ACTIVE = [{"slot": "05", "state": "active"}, {"slot": "06", "state": "waiting"}]


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        patch = mock.patch.object(checks, "folder", lambda main: self.dir)
        patch.start()
        self.addCleanup(patch.stop)

    def defer(self, slot="13", minutes=0, title=None, **kw):
        at = NOW + dt.timedelta(minutes=minutes)
        return checks.append("/m", "deferred", slot, at, id=checks.new_id(slot, at), pane=f"%{slot}",
                             title=title or f"[{slot}] ci-check plan", argv=ARGV, cwd="/w", **kw)

    def state(self, busy=None, runs=(), panes=None):
        return {"busy": busy, "runs": list(runs), "rows": checks.lines("/m"), "panes": panes or {}}

    def plan(self, s, jobs=None, log=(), now=NOW):
        planned = checks.plan("/m", {**s, "log": list(log)}, lambda rid: (jobs or {}).get(rid, []), now)
        return tick.fresh(planned, list(log), now.replace(tzinfo=None))


class Busy(unittest.TestCase):
    def test_what_holds_the_runners_for_the_landings(self):
        self.assertEqual(checks.busy(ACTIVE, None, [])["slot"], "05")
        reserved = [{"slot": "wm", "state": "held", "hold": {"reason": "reserved"}}]
        self.assertIn("holds the merge queue", checks.busy(reserved, None, [])["reason"])
        train = {"train": "06+05@x", "state": "landing", "carrier": "tollman-hal2"}
        self.assertEqual(checks.busy([], train, []), {"reason": "the train 06+05@x stands",
                                                      "slot": "tollman-hal2"})
        push = [{"event": "push", "headBranch": "land/07", "status": "in_progress", "databaseId": 9}]
        self.assertEqual(checks.busy([], None, push)["slot"], "07")
        self.assertEqual(checks.busy([{"slot": "06", "state": "waiting"}], None, [])["slot"], "06")

    def test_free_when_nothing_lands_or_a_red_landing_holds_the_queue(self):
        self.assertIsNone(checks.busy([], None, [check_run(1, status="in_progress")]))
        self.assertIsNone(checks.busy([], {"state": "red"}, [{"event": "push", "headBranch": "land/07",
                                                               "status": "completed"}]))
        red = [{"slot": "04", "state": "held", "hold": {"reason": "failed"}}, {"slot": "05", "state": "waiting"}]
        self.assertIsNone(checks.busy(red, None, []), "a red holder moves nothing: the checks may run")

    def test_a_check_counts_as_started_only_with_a_lane_job(self):
        self.assertFalse(checks.lane_started([ROUTE, CHANGES, SKIPPED, {"name": "x/rust-test", "status": "queued"}]))
        self.assertTrue(checks.lane_started([ROUTE, CHANGES, LANE]))
        # The names since plan 0349 D101: `<matrix alias>-<NN>-<job>`, route and changes as ci-route and ci-changes.
        route, changes = {**ROUTE, "name": "a1-01-ci-route"}, {**CHANGES, "name": "b1-01-ci-changes"}
        self.assertFalse(checks.lane_started([route, changes, {**SKIPPED, "name": "c2-08-rust-test"}]))
        self.assertTrue(checks.lane_started([route, changes, {**LANE, "name": "c2-08-rust-test"}]))


class Holds(Store):
    def dispatched(self, rid=None, **kw):
        return checks.append("/m", "dispatched", "13", NOW, id=checks.new_id("13", NOW), pane="%13",
                             title="[13] ci-check 0306 1/6", argv=ARGV, cwd="/w", by="ci-check", run=rid, **kw)

    def test_a_queued_check_is_cancelled_while_a_landing_is_active(self):
        self.dispatched(41)
        held = checks.busy(ACTIVE, None, [])
        acts = self.plan(self.state(held, [check_run(41)]), {41: [ROUTE, CHANGES]})
        self.assertEqual([(a["do"], a["kind"], a["slot"]) for a in acts], [("run", "check-cancel", "13")])
        self.assertEqual(acts[0]["argv"][-5:], ["cancel", "--run", "41", "--repo", "/m"])
        self.assertEqual(self.plan(self.state(held, [check_run(41)]), log=[{"at": "2026-10-14T10:05:00",
                                                                             "key": "checks-cancel:41"}]), [])

    def test_a_check_with_a_started_lane_job_is_left_alone(self):
        self.dispatched(41)
        s = self.state(checks.busy(ACTIVE, None, []), [check_run(41, status="in_progress")])
        self.assertEqual(self.plan(s, {41: [ROUTE, CHANGES, LANE]}), [])

    def test_a_check_not_in_the_store_is_only_logged_and_matched_by_title_otherwise(self):
        s = self.state(checks.busy(ACTIVE, None, []), [check_run(42)])
        self.assertEqual([(a["do"], a["kind"]) for a in self.plan(s)], [("record", "check-unknown")])
        self.dispatched(None)  # ci-check recorded its dispatch without the run id: the title finds it
        s = self.state(checks.busy(ACTIVE, None, []), [check_run(42)])
        self.assertEqual([a["kind"] for a in self.plan(s)], ["check-cancel"])

    def test_cancel_re_checks_cancels_and_defers_again_and_the_session_is_told_once(self):
        self.dispatched(41)
        calls = []
        view = {**check_run(41), "jobs": [ROUTE, CHANGES]}
        code, text = checks_cli.cancel("/m", 41, run=lambda argv, cwd: calls.append(argv) or (0, ""),
                                       run_json=lambda args, cwd: view, now=NOW)
        self.assertEqual((code, calls), (0, [["gh", "run", "cancel", "41"]]), text)
        again = checks.pending(checks.lines("/m"))
        self.assertEqual([(e["slot"], e["again"], e["argv"]) for e in again], [("13", 41, ARGV)])
        held = checks.busy(ACTIVE, None, [])
        acts = self.plan(self.state(held, panes={"13": "%99"}))
        self.assertEqual([(a["do"], a["kind"], a["pane"]) for a in acts], [("send", "check-waits", "%99")])
        self.assertIn("the landing of 05 runs", acts[0]["text"])
        self.assertEqual(self.plan(self.state(held), log=[{"at": "2026-10-14T10:02:00", "key": acts[0]["key"]}]), [])

    def test_cancel_is_refused_once_a_lane_job_started_or_for_a_run_not_recorded(self):
        self.dispatched(41)
        never = lambda argv, cwd: self.fail(f"ran {argv}")  # noqa: E731
        view = {**check_run(41), "jobs": [ROUTE, LANE]}
        self.assertEqual(checks_cli.cancel("/m", 41, run=never, run_json=lambda a, c: view, now=NOW)[0], 1)
        other = {**check_run(43, title="[09] ci-check other"), "jobs": [ROUTE]}
        self.assertEqual(checks_cli.cancel("/m", 43, run=never, run_json=lambda a, c: other, now=NOW)[0], 1)
        self.assertEqual(checks.pending(checks.lines("/m")), [])


class Dispatch(Store):
    def test_after_the_landing_the_oldest_slot_s_newest_deferral_is_dispatched_and_the_session_told(self):
        self.defer("13", 0, title="[13] ci-check old")
        self.defer("09", 1)
        newest = self.defer("13", 2, title="[13] ci-check 0306 1/6")
        acts = self.plan(self.state())
        self.assertEqual([(a["do"], a["kind"], a["slot"]) for a in acts], [("run", "check-dispatch", "13")])
        self.assertEqual(acts[0]["argv"][-4:-2], ["--id", newest["id"]])
        ran, listed = [], [{**check_run(77), "createdAt": "2099-01-01T00:00:00Z"}]
        code, text = checks_cli.dispatch("/m", newest["id"], run=lambda argv, cwd: ran.append((argv, cwd)) or (0, ""),
                                         run_json=lambda args, cwd: listed, sleep=lambda s: None, now=NOW)
        self.assertEqual((code, ran), (0, [(ARGV, "/w")]), text)
        rows = checks.lines("/m")
        self.assertEqual([e["slot"] for e in checks.pending(rows)], ["09"], "13's older deferral superseded")
        acts = self.plan(self.state())
        self.assertEqual([(a["do"], a["kind"], a["slot"]) for a in acts],
                         [("run", "check-dispatch", "09"), ("send", "check-runs", "13")])
        self.assertIn("runs: https://x/runs/77", acts[1]["text"])
        told = [{"at": "2026-10-14T10:03:00", "key": a["key"]} for a in acts]
        self.assertEqual(self.plan(self.state(), log=told), [], "keys dedupe across rounds")

    def test_a_failed_dispatch_is_tried_again_later_and_given_up_after_three_tries(self):
        d = self.defer("13")
        other = self.defer("09", 1)
        for n in range(checks.TRIES):
            at = NOW + n * checks.RETRY
            self.assertEqual(checks.next_dispatch(checks.lines("/m"), at)["id"], d["id"], f"try {n + 1}")
            code, text = checks_cli.dispatch("/m", d["id"], run=lambda argv, cwd: (1, "HTTP 500"),
                                             run_json=lambda a, c: [], sleep=lambda s: None, now=at)
            self.assertEqual(code, 1, text)
            if n == 0:  # within RETRY the failed slot blocks no other slot
                self.assertEqual(checks.next_dispatch(checks.lines("/m"), at)["id"], other["id"])
        rows = checks.lines("/m")
        self.assertEqual([r["attempt"] for r in checks.attempts(rows, d["id"])], [1, 2, 3])
        self.assertEqual([e["slot"] for e in checks.pending(rows)], ["09"], "13's deferral given up for good")
        acts = [a for a in self.plan(self.state(), now=NOW + 3 * checks.RETRY) if a["kind"] == "check-failed"]
        self.assertEqual([(a["do"], a["pane"]) for a in acts], [("send", "%13")])
        self.assertIn("could not be dispatched: exit 1: HTTP 500; run ci-check again", acts[0]["text"])

    def test_one_duty_dispatch_at_a_time(self):
        self.defer("09")
        checks.append("/m", "dispatched", "13", NOW, id="13-1", pane="%13", title="[13] ci-check a", argv=ARGV,
                      by="checks", run=77)
        running = [check_run(77, title="[13] ci-check a", status="in_progress")]
        self.assertEqual([a["kind"] for a in self.plan(self.state(runs=running))], ["check-runs"])
        done = [check_run(77, title="[13] ci-check a", status="completed")]
        self.assertEqual([a["kind"] for a in self.plan(self.state(runs=done))], ["check-dispatch", "check-runs"])
        checks.append("/m", "dispatched", "13", NOW, id="13-2", title="[13] ci-check b", argv=ARGV, by="checks")
        self.assertNotIn("check-dispatch", [a["kind"] for a in self.plan(self.state(runs=done))],
                         "a duty dispatch whose run is not listed yet counts as running")
        self.assertIn("check-dispatch", [a["kind"] for a in self.plan(self.state(runs=done),
                                                                     now=NOW + checks.MATCH * 2)])

    def test_a_recorded_dispatch_supersedes_the_slot_s_deferrals_and_a_stale_one_is_never_sent(self):
        self.defer("13")
        args = mock.Mock(checks="dispatched", argv=ARGV, pane="%13", title="[13] ci-check x", cwd="/w", repo="/w",
                         slot="13", run=5, url=None)
        line = checks_cli.record("/m", args)
        rows = checks.lines("/m")
        self.assertEqual((checks.pending(rows), rows[-1]["kind"], rows[-1]["by"]), ([], "superseded", line["id"]))
        old = self.defer("09")
        never = lambda argv, cwd: self.fail(f"ran {argv}")  # noqa: E731
        code, text = checks_cli.dispatch("/m", old["id"], run=never, now=NOW + checks.STALE + checks.RETRY)
        self.assertEqual((code, checks.pending(checks.lines("/m"))), (1, []), text)
        self.assertEqual(checks.lines("/m")[-1]["by"], "stale")

    def test_a_failed_gh_run_list_is_busy_and_dispatches_nothing(self):
        self.assertIsNone(checks.runs(lambda a, c: None, "/m"))
        self.assertEqual(checks.runs(lambda a, c: [], "/m"), [])
        self.assertEqual(checks.busy([], None, None), {"reason": checks.GH_FAILED, "slot": ""})
        self.defer("13")
        self.assertEqual(self.plan({**self.state(checks.busy([], None, None)), "runs": None}), [])

    def test_while_busy_nothing_is_dispatched(self):
        self.defer("13")
        self.assertEqual(self.plan(self.state(checks.busy(ACTIVE, None, []))), [])


class Waiting(unittest.TestCase):
    def test_a_waiting_ticket_holds_only_while_young_or_its_session_lives(self):
        old = [{"slot": "06", "state": "waiting", "enqueued": "2026-10-14T07:00:00Z"}]
        self.assertIsNone(checks.busy(old, None, [], NOW, set()), "3 h old, no session: the runners are free")
        self.assertEqual(checks.busy(old, None, [], NOW, {"06"})["slot"], "06")
        young = [{**old[0], "ready": {"at": "2026-10-14T09:00:00Z"}}]
        self.assertEqual(checks.busy(young, None, [], NOW, set())["slot"], "06")


class SessionsOf(unittest.TestCase):
    def test_the_list_s_agents_object_and_the_bare_array_both_name_the_worktrees(self):
        home = Path.home() / ".hal/git/worktree/hal2"
        rows = [{"slot": "07", "checkout": str(home / "07")}, {"slot": "08", "checkout": "/elsewhere/08"}]
        for body in ({"agents": rows}, rows):
            with mock.patch.object(checks.deliver, "cli", lambda *a: (0, json.dumps(body))):
                self.assertEqual(checks.sessions_of("/Users/x/a/hal2"), {"07"})


class Tells(Store):
    def test_a_relayed_tell_goes_out_again_after_the_window_a_typed_one_never(self):
        checks.append("/m", "dispatched", "13", NOW, id="13-1", pane="%13", title="[13] ci-check a", argv=ARGV,
                      by="checks", run=77, url="https://x/runs/77")
        relayed = [{"at": "2026-10-14T10:00:00", "key": "checks-runs:13-1", "do": "relay"}]
        self.assertEqual(self.plan(self.state(), log=relayed, now=NOW + dt.timedelta(minutes=10)), [])
        later = NOW + checks_tell.SEND_WINDOW + dt.timedelta(minutes=1)
        self.assertEqual([a["kind"] for a in self.plan(self.state(), log=relayed, now=later)], ["check-runs"])
        typed = [{**relayed[0], "do": "send"}]
        self.assertEqual(self.plan(self.state(), log=typed, now=later), [])
        self.assertEqual(self.plan(self.state(), log=relayed * checks_tell.SEND_TRIES, now=later), [])


class Cli(Store):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(checks, "sessions_of", lambda main: set())
        patch.start()
        self.addCleanup(patch.stop)

    def main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = tollman.main(list(argv))
        return code, out.getvalue()

    def fake(self, args, cwd):
        return {"queue": ACTIVE} if args[:3] == ["hal2-cli-git", "worktree", "queue"] else []

    def status(self, field: Path, loaded=True, age=60):
        return lambda repo: {"field": str(field), "field_exists": field.is_dir(), "timer": {"loaded": loaded},
                             "mode": "timer", "last_tick_age_s": age}

    def test_checks_busy_json_says_busy_and_live(self):
        field = self.dir / "tollman-hal2"
        (field / "roles/tollman").mkdir(parents=True)
        (field / "roles/tollman/ROLE.md").write_text('---\nduties:\n  checks: "*/2 * * * *"\n---\n')
        with mock.patch.object(mtm_scan, "run_json", self.fake), \
                mock.patch.object(mtm_scan, "main_checkout", lambda repo: repo), \
                mock.patch.object(tollman, "status", self.status(field)):
            code, out = self.main("checks", "busy", "--json", "--repo", str(self.dir))
            self.assertEqual((code, json.loads(out)), (0, {"busy": True, "reason": "the landing of 05 runs",
                                                           "slot": "05", "live": True, "live_why": ""}))
            (field / "roles/tollman/ROLE.md").write_text('---\nduties:\n  mtm: "*/2 * * * *"\n---\n')
            self.assertIn("not opted in", json.loads(self.main("checks", "busy", "--json", "--repo", str(self.dir))[1])
                          ["live_why"])
        with mock.patch.object(mtm_scan, "run_json", self.fake), \
                mock.patch.object(mtm_scan, "main_checkout", lambda repo: repo), \
                mock.patch.object(tollman, "status", self.status(field, age=4000)):
            self.assertFalse(json.loads(self.main("checks", "busy", "--json", "--repo", str(self.dir))[1])["live"])

    def test_checks_defer_and_list(self):
        with mock.patch.object(mtm_scan, "main_checkout", lambda repo: repo):
            code, out = self.main("checks", "defer", "--slot", "13", "--pane", "%5", "--title", "[13] ci-check x",
                                  "--repo", str(self.dir), "--", *ARGV)
            self.assertEqual(code, 0)
            listed = json.loads(self.main("checks", "list", "--json", "--repo", str(self.dir))[1])
        [e] = listed["pending"]
        self.assertEqual((e["id"], e["argv"], e["pane"], e["schema"]), (out.strip(), ARGV, "%5", 1))


if __name__ == "__main__":
    unittest.main()
