"""Hal2 plan 0515: the farmer tick crashed (`can't compare offset-naive and offset-aware datetimes`) on a log mixing
naive local stamps (the writers' `datetime.now()`) with hand-written zoned ones. `mtm_scan.log_time` reads both (D1)."""

import datetime as dt
import unittest
from pathlib import Path

import logstate
import mtm_scan
import tick

import sys
sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import repo_root, sibling  # noqa: E402,F401  (the skills unit's scripts/, plan 0360 D20)

NOW = dt.datetime(2026, 10, 30, 19, 0, 0)


def local(*a) -> dt.datetime:
    return dt.datetime(*a)


def zoned(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


class LogTime(unittest.TestCase):
    def test_naive_is_kept(self):
        self.assertEqual(mtm_scan.log_time("2026-10-30T18:54:49"), dt.datetime(2026, 10, 30, 18, 54, 49))

    def test_zoned_becomes_naive_local(self):
        t = local(2026, 10, 30, 18, 54, 49)
        for text in (zoned(t), zoned(t).replace("+00:00", "Z")):
            got = mtm_scan.log_time(text)
            self.assertIsNone(got.tzinfo)
            self.assertEqual(got, t)

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            mtm_scan.log_time("yesterday")


class Fresh(unittest.TestCase):
    ACTION = {"key": "k", "do": "send", "slot": "07", "kind": "x", "window": 3600}

    def test_mixed_log_does_not_raise(self):
        log = [{"at": "2026-10-30T18:54:49", "key": "k"}, {"at": zoned(local(2026, 10, 30, 18, 10)), "key": "k"}]
        self.assertEqual(tick.fresh([self.ACTION], log, NOW), [])  # 18:54 is inside the hour

    def test_real_instant_decides(self):
        old_zoned = zoned(local(2026, 10, 30, 12, 0))
        log = [{"at": old_zoned, "key": "k"}, {"at": "2026-10-30T11:00:00", "key": "k"}]
        self.assertEqual([a["key"] for a in tick.fresh([self.ACTION], log, NOW)], ["k"])
        log = [{"at": "2026-10-30T11:00:00", "key": "k"}, {"at": zoned(local(2026, 10, 30, 18, 30)), "key": "k"}]
        self.assertEqual(tick.fresh([self.ACTION], log, NOW), [])


class Paused(unittest.TestCase):
    def test_mixed_log(self):
        log = [{"at": zoned(local(2026, 10, 30, 17, 0)), "key": "pause:L1:07"},
               {"at": "2026-10-30T18:00:00", "key": "pause:L2:08"},
               {"at": "2026-10-30T18:30:00", "key": "go:L2:08"}]
        self.assertEqual(logstate.paused(log, NOW), {"07"})


class Entries(unittest.TestCase):
    def test_garbage_line_skipped_zoned_kept(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "log.jsonl"
            p.write_text('{"at": "2026-10-30T18:00:00+00:00"}\n{"at": "nope"}\n{"at": "2026-10-30T18:00:00"}\n')
            self.assertEqual(len(mtm_scan.entries(p)), 2)


if __name__ == "__main__":
    unittest.main()
