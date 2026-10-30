"""Hal2 plan 0480 step 01.03 (D1): pass_timing, the minute pass's wall, process starts and gh calls in
pass-timing.jsonl, kept to a day of passes."""
# enforces .adr/deterministic-first.md and .adr/stores-have-a-retention.md

import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pass_timing

NOW = dt.datetime(2026, 10, 30, 12, 0, 5, tzinfo=dt.timezone.utc)


class Counting(unittest.TestCase):
    def setUp(self):
        self.addCleanup(pass_timing.abandon)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, True))

    def test_nothing_is_counted_outside_a_pass(self):
        pass_timing.count_gh(["gh", "run", "list"])
        self.assertIsNone(pass_timing.record())
        self.assertIsNone(pass_timing.finish(self.dir, NOW))
        self.assertFalse((self.dir / pass_timing.FILE).exists())

    def test_it_counts_process_starts_in_any_thread_and_only_gh_commands(self):
        pass_timing.begin()
        subprocess.run([sys.executable, "-c", "pass"], check=True)
        subprocess.check_output([sys.executable, "-c", "pass"])
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda _: subprocess.run([sys.executable, "-c", "pass"]), range(3)))
        pass_timing.count_gh(["gh", "api", "x"])
        pass_timing.count_gh(["git", "status"])
        pass_timing.count_gh([])
        rec = pass_timing.finish(self.dir, NOW)
        self.assertEqual((rec["procs"], rec["gh"], rec["schema"], rec["at"]), (5, 1, 1, "2026-10-30T12:00:05Z"))
        self.assertGreaterEqual(rec["wall_ms"], 0)
        self.assertEqual(json.loads((self.dir / pass_timing.FILE).read_text()), rec)
        subprocess.run([sys.executable, "-c", "pass"])  # after finish: not counted, and Popen is whole again
        self.assertIsNone(pass_timing.record())
        self.assertIs(subprocess.Popen.__init__, pass_timing._init)

    def test_an_abandoned_pass_leaves_no_record_and_a_new_pass_starts_at_zero(self):
        pass_timing.begin()
        pass_timing.count_gh(["gh"])
        pass_timing.abandon()
        pass_timing.begin()
        self.assertEqual((pass_timing.record()["procs"], pass_timing.record()["gh"]), (0, 0))

    def test_an_unwritable_folder_never_raises(self):
        pass_timing.begin()
        self.assertEqual(pass_timing.finish(self.dir / "missing", NOW)["procs"], 0)


class Retention(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, True))
        self.path = self.dir / pass_timing.FILE

    def write(self, n):
        self.path.write_text("".join(json.dumps({"schema": 1, "at": "x", "wall_ms": i, "procs": 1, "gh": 0}) + "\n"
                                     for i in range(n)))

    def test_trim_keeps_the_last_day_once_it_is_a_tenth_over(self):
        self.write(1440 + 100)
        pass_timing.trim(self.path)
        self.assertEqual(len(self.path.read_text().splitlines()), 1440 + 100, "within a tenth over: left alone")
        self.write(1440 + 200)
        pass_timing.trim(self.path)
        rows = pass_timing.read(self.path)
        self.assertEqual((len(rows), rows[0]["wall_ms"], rows[-1]["wall_ms"]), (1440, 200, 1639))
        self.assertEqual([p.name for p in self.dir.iterdir()], [pass_timing.FILE], "no temp file left")

    def test_finish_trims_a_big_file(self):
        self.write(2000)
        pass_timing.begin()
        pass_timing.finish(self.dir, NOW)
        self.assertLessEqual(len(self.path.read_text().splitlines()), 1440 + 144)


class Summary(unittest.TestCase):
    def test_median_and_p95_per_field(self):
        rows = [{"wall_ms": 100 * (i + 1), "procs": 7, "gh": i % 2} for i in range(10)]
        s = pass_timing.summary(rows)
        self.assertEqual(s["passes"], 10)
        self.assertEqual(s["wall_ms"], {"median": 550, "p95": 1000})
        self.assertEqual((s["procs"], s["gh"]), ({"median": 7, "p95": 7}, {"median": 0.5, "p95": 1}))
        self.assertEqual(pass_timing.summary([]), {"passes": 0})

    def test_a_torn_or_foreign_line_is_skipped(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, True))
        f = d / "t.jsonl"
        f.write_text('{"wall_ms": 5, "procs": 1, "gh": 0}\n{"wall_\n[1]\n{"wall_ms": "x"}\n')
        self.assertEqual(pass_timing.summary(pass_timing.read(f))["passes"], 1)
        self.assertEqual(pass_timing.read(d / "none"), [])


if __name__ == "__main__":
    unittest.main()
