"""Plan 0333 step 7: a tick round takes one `mtm_scan.snapshot`, not two (the summary reuses the scan the mtm duty
wrote to last-scan.json this round; 63 of the tollman's 168 tick minutes on 2026-10-14 were the second one)."""

import json
import os
import time
import unittest
from unittest import mock

import mtm_scan
import scan_cache
import tasks
import tick
from test_farmer import NOW, Repo

SNAP = {"now": 1.0, "repo": "/x", "queue": [], "findings": [], "landings": [], "worktrees": [],
        "load": {"load1": 1.0, "cores": 8}}


class Cache(Repo):
    def scan_file(self, snap=None, age=0.0, raw=None):
        f = mtm_scan.state_dir(str(self.main), "farmer") / "last-scan.json"
        f.write_text(raw if raw is not None else json.dumps(snap or {**SNAP, "marker": "file"}))
        os.utime(f, (time.time() - age,) * 2)
        return f

    def take(self, since=None):
        with mock.patch.object(mtm_scan, "snapshot", return_value={**SNAP, "marker": "new"}) as snap:
            got = scan_cache.scan(str(self.slot), "farmer", since)
        return got["marker"], snap.call_count

    def test_a_fresh_file_is_read_back_without_a_snapshot(self):
        self.scan_file(age=60)
        self.assertEqual(self.take(), ("file", 0))

    def test_a_missing_stale_or_broken_file_takes_a_new_snapshot(self):
        self.assertEqual(self.take(), ("new", 1))  # missing
        self.scan_file(age=scan_cache.FRESH_S + 60)
        self.assertEqual(self.take(), ("new", 1))  # older than the cap, no round start
        self.scan_file(raw="{not json")
        self.assertEqual(self.take(), ("new", 1))
        self.scan_file(raw="[1, 2]")
        self.assertEqual(self.take(), ("new", 1))

    def test_the_cap_is_ten_minutes_with_or_without_a_round_start(self):
        self.assertEqual(scan_cache.FRESH_S, 600)
        self.scan_file(age=540)
        self.assertEqual(self.take(since=time.time()), ("file", 0), "written before the round, still young")
        self.scan_file(age=660)
        self.assertEqual(self.take(since=time.time()), ("new", 1))

    def test_with_a_round_start_the_files_age_is_judged_against_it(self):
        start = time.time() - 900  # a long round: the scan from its start is still this round's
        self.scan_file(age=600)
        self.assertEqual(self.take(since=start), ("file", 0))
        self.scan_file(age=1000)  # written before the round began: the last round's
        self.assertEqual(self.take(since=start), ("new", 1))

    def test_the_orphans_check_reuses_the_scan_too(self):
        self.scan_file(snap={**SNAP, "repo": str(self.main), "findings": [{"kind": "work-without-agent",
                                                                           "slot": "13", "why": "w"}]})
        with mock.patch.object(mtm_scan, "snapshot", side_effect=AssertionError("a second snapshot")):
            self.assertEqual([f["slot"] for f in tasks.orphans(str(self.slot))], ["13"])


class OneSnapshotPerRound(Repo):
    def round(self, writes_scan=True):
        """A round whose mtm duty takes the round's snapshot and keeps it, as boss.handler does."""
        real = tick.sh

        def sh(argv, cwd, timeout=900):
            return (0, json.dumps({"status": "ok"})) if argv[0] == "hal2-cli-git" else real(argv, cwd, timeout)

        def duty(item, ctx):
            snap = mtm_scan.snapshot(ctx["top"], 24, fetch=not ctx["dry"])
            if writes_scan:
                (mtm_scan.state_dir(ctx["main"], "farmer") / "last-scan.json").write_text(json.dumps(snap))
            return []

        with mock.patch.object(tick, "sh", sh), \
                mock.patch.object(mtm_scan, "snapshot", return_value=dict(SNAP)) as snapshot:
            r = tick.run(str(self.slot), False, {"duty:lead": duty}, NOW)
        return r, snapshot.call_count

    def test_a_round_with_the_mtm_duty_takes_exactly_one_snapshot(self):
        r, calls = self.round()
        self.assertEqual(calls, 1)
        self.assertIn("hal2/summaries/", r["summary"])  # and the summary was still written

    def test_a_round_whose_duty_left_no_scan_takes_the_summary_s_own(self):
        _, calls = self.round(writes_scan=False)
        self.assertEqual(calls, 2)

    def test_a_scan_of_the_last_round_under_ten_minutes_old_serves_the_summary(self):
        # plan 0480 step 02.02: a round whose mtm duty was not due (or left no scan) reuses last-scan.json
        f = mtm_scan.state_dir(str(self.main), "farmer") / "last-scan.json"
        f.write_text(json.dumps(SNAP))
        os.utime(f, (time.time() - 540,) * 2)  # written before this round began, still under FRESH_S (10 min)
        _, calls = self.round(writes_scan=False)
        self.assertEqual(calls, 1, "the duty's own snapshot only (it keeps none here); the summary took none")

    def test_a_scan_older_than_ten_minutes_does_not(self):
        f = mtm_scan.state_dir(str(self.main), "farmer") / "last-scan.json"
        f.write_text(json.dumps(SNAP))
        os.utime(f, (time.time() - scan_cache.FRESH_S - 60,) * 2)
        _, calls = self.round(writes_scan=False)
        self.assertEqual(calls, 2, "the duty's snapshot and the summary's own")


if __name__ == "__main__":
    unittest.main()
