import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

import gh_runs
import mtm_ci


def run(rid, branch, status="completed", conclusion="failure", at="2026-10-05T06:00:00Z"):
    return {"databaseId": rid, "headBranch": branch, "headSha": "a" * 40, "status": status,
            "conclusion": conclusion, "createdAt": at, "url": f"https://x/runs/{rid}"}


class Fake:
    """gh as `run_json(args, cwd)`: counts the calls, answers a list and each run's jobs."""

    def __init__(self, runs, delay=0.0):
        self.runs, self.delay, self.calls, self.lock = runs, delay, [], threading.Lock()
        self.running = self.most = 0

    def __call__(self, args, cwd):
        with self.lock:
            self.calls.append(args[:3])
            self.running += 1
            self.most = max(self.most, self.running)
        time.sleep(self.delay)
        with self.lock:
            self.running -= 1
        if args[:3] == ["gh", "run", "list"]:
            return self.runs
        return {"jobs": [{"name": f"gate-{args[3]}", "conclusion": "failure"}]}

    def views(self):
        return sum(1 for c in self.calls if c == ["gh", "run", "view"])


class GhRunsTest(unittest.TestCase):
    RUNS = [run(1, "land/07"), run(2, "land/03"), run(3, "land/05", status="in_progress", conclusion=""),
            run(4, "land/09", conclusion="success")]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "cache" / "run-jobs"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_round_fetches_each_list_and_each_runs_jobs_once(self):
        gh = Fake(self.RUNS)
        with gh_runs.round(self.cache) as stats:
            first = mtm_ci.landings(gh, "/m", 0)
            again = mtm_ci.landings(gh, "/m", 0)  # trains, the orphans task, the summary: the same calls
        self.assertEqual(first, again)
        self.assertEqual([(r["slot"], r["outcome"], r["task"]) for r in first],
                         [("07", "failed", "gate-1"), ("03", "failed", "gate-2"), ("05", "running", ""),
                          ("09", "landed", "")])
        self.assertEqual((stats["list"], stats["view"], stats["cached"], gh.views()), (1, 3, 0, 3))

    def test_a_completed_runs_jobs_come_from_the_disk_next_round_a_running_one_is_fetched_again(self):
        with gh_runs.round(self.cache):
            mtm_ci.landings(Fake(self.RUNS), "/m", 0)
        self.assertEqual(sorted(p.name for p in self.cache.glob("*.json")), ["1.json", "2.json"])
        gh = Fake(self.RUNS)
        with gh_runs.round(self.cache) as stats:
            rows = mtm_ci.landings(gh, "/m", 0)
        self.assertEqual((stats["view"], stats["cached"]), (1, 2))  # only the running run 3
        self.assertEqual(rows[0]["task"], "gate-1")

    def test_uncached_runs_are_fetched_in_parallel(self):
        runs = [run(i, f"land/{i:02}") for i in range(1, 7)]
        gh = Fake(runs, delay=0.2)
        start = time.monotonic()
        with gh_runs.round(None):
            mtm_ci.landings(gh, "/m", 0)
        self.assertGreater(gh.most, 1)
        self.assertLess(time.monotonic() - start, 0.2 * 6)

    def test_outside_a_round_every_call_fetches_and_nothing_is_written(self):
        gh = Fake(self.RUNS)
        mtm_ci.landings(gh, "/m", 0)
        mtm_ci.landings(gh, "/m", 0)
        self.assertEqual(gh.views(), 6)
        self.assertFalse(self.cache.exists())

    def test_old_cache_files_are_removed(self):
        self.cache.mkdir(parents=True)
        old, new = self.cache / "1.json", self.cache / "2.json"
        for f in (old, new):
            f.write_text("[]")
        stale = time.time() - gh_runs.KEEP - 60
        os.utime(old, (stale, stale))
        with gh_runs.round(self.cache):
            pass
        self.assertEqual([p.name for p in self.cache.glob("*.json")], ["2.json"])

    def test_the_cache_folder_needs_the_state_folder(self):
        self.assertIsNone(gh_runs.cache_dir(Path(self.tmp.name) / "missing"))
        self.assertEqual(gh_runs.cache_dir(Path(self.tmp.name)), self.cache)


if __name__ == "__main__":
    unittest.main()
