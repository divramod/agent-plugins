"""Field sizes (sizes.py; hal2 plan 0377 step 3, D9, D18): the budgeted walk, the lower bound, the cache by HEAD and
mtime, the parallel measure. Temp trees only, a fake clock for the budget; no load is generated."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import sizes


def tree(files: dict[str, int]) -> Path:
    root = Path(tempfile.mkdtemp())
    for rel, n in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x" * n)
    return root


class Walk(unittest.TestCase):
    def test_counts_files_and_bytes_of_the_whole_tree(self):
        root = tree({"a": 10_000, "d/b": 20_000, "d/e/c": 30_000})
        r = sizes.walk(root)
        self.assertEqual((r["files"], r["lower_bound"]), (3, False))
        self.assertGreaterEqual(r["bytes"], 60_000)
        self.assertLess(r["bytes"], 60_000 + 3 * 64_000)  # allocated blocks round up

    def test_symlinks_are_not_followed_and_a_hard_link_counts_once(self):
        root = tree({"a": 10_000})
        os.symlink(root, root / "loop")
        os.link(root / "a", root / "b")
        r = sizes.walk(root)
        self.assertEqual(r["files"], 2)  # a (once for both names) and the symlink itself
        self.assertFalse(r["lower_bound"])

    def test_an_unreadable_folder_is_skipped(self):
        root = tree({"a": 1, "locked/b": 1})
        (root / "locked").chmod(0)
        self.addCleanup((root / "locked").chmod, 0o755)
        self.assertEqual(sizes.walk(root)["files"], 1 if os.geteuid() else 2)

    def test_over_budget_a_lower_bound(self):
        root = tree({f"d{i}/f": 1 for i in range(5)})
        ticks = iter(range(0, 1000, 5))  # the clock jumps 5 s per look
        r = sizes.walk(root, budget=7, clock=lambda: next(ticks))
        self.assertTrue(r["lower_bound"])
        self.assertLess(r["files"], 5)

    def test_a_big_folder_is_stopped_by_the_entry_check(self):
        root = tree({})
        for i in range(sizes.CHECK_EVERY + 5):
            (root / f"f{i}").write_bytes(b"")
        ticks = iter(range(0, 1000, 10))
        r = sizes.walk(root, budget=7, clock=lambda: next(ticks))
        self.assertTrue(r["lower_bound"])

    def test_human(self):
        self.assertEqual(sizes.human(512), "512 B")
        self.assertEqual(sizes.human(12_340_000_000), "12.3 GB")
        self.assertEqual(sizes.human({"bytes": 5_000_000, "lower_bound": True}), "≥ 5.0 MB")
        self.assertEqual(sizes.human(None), "unknown")


class Measure(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        patcher = mock.patch.dict(os.environ, {"HAL_PRUNE_DIR": self.state})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.main = Path(tempfile.mkdtemp()) / "farm"
        self.root = tree({"a": 10_000, "d/b": 20_000})
        self.field = {"slot": "13", "path": str(self.root), "head": "abc"}

    def measure(self, **kw):
        return sizes.measure_all(self.main, [self.field], **kw)["13"]

    def test_the_second_measure_comes_from_the_cache_while_head_and_mtime_match(self):
        first = self.measure()
        self.assertFalse(first["cached"])
        with mock.patch.object(sizes, "walk", side_effect=AssertionError("walked again")):
            second = self.measure()
        self.assertTrue(second["cached"])
        self.assertEqual(second["bytes"], first["bytes"])

    def test_a_new_head_or_a_changed_root_or_an_old_entry_is_measured_again(self):
        first = self.measure()
        self.field["head"] = "def"
        self.assertFalse(self.measure()["cached"])
        (self.root / "new").write_bytes(b"y" * 50_000)
        os.utime(self.root, (time.time() + 5, time.time() + 5))
        grown = self.measure()
        self.assertFalse(grown["cached"])
        self.assertGreater(grown["bytes"], first["bytes"])
        self.assertFalse(self.measure(now=time.time() + sizes.CACHE_TTL + 10)["cached"])

    def test_a_lower_bound_is_never_cached(self):
        with mock.patch.object(sizes, "walk", return_value={"bytes": 5, "files": 1, "lower_bound": True}):
            self.assertTrue(self.measure()["lower_bound"])
        again = self.measure()
        self.assertFalse(again["cached"])
        self.assertFalse(again["lower_bound"])

    def test_the_cache_holds_only_the_fields_given(self):
        self.measure()
        other = tree({"z": 1})
        sizes.measure_all(self.main, [{"slot": "14", "path": str(other), "head": "h"}])
        cache = sizes.store.read_json(sizes.store.state_dir(self.main) / sizes.CACHE_FILE, {})
        self.assertEqual(list(cache), [str(other)])

    def test_many_fields_in_a_pool_of_at_most_half_the_cores(self):
        fields = [{"slot": f"{i:02d}", "path": str(tree({"f": 1})), "head": "h"} for i in range(10, 16)]
        with mock.patch.object(sizes.os, "cpu_count", return_value=8):
            self.assertEqual(sizes.workers(), 4)
        with mock.patch.object(sizes.os, "cpu_count", return_value=1):
            self.assertEqual(sizes.workers(), 1)
        got = sizes.measure_all(self.main, fields, pool=2)
        self.assertEqual(sorted(got), [f["slot"] for f in fields])
        self.assertTrue(all(v["files"] == 1 for v in got.values()))

    def test_cached_only_gives_hits_and_none_for_a_miss_and_never_walks_or_writes(self):
        with mock.patch.object(sizes, "walk", side_effect=AssertionError("walked")):
            self.assertIsNone(self.measure(cached_only=True))
        first = self.measure()
        cache_file = sizes.store.state_dir(self.main) / sizes.CACHE_FILE
        before = cache_file.read_text()
        other = {"slot": "14", "path": str(tree({"z": 1})), "head": "h"}
        with mock.patch.object(sizes, "walk", side_effect=AssertionError("walked")):
            got = sizes.measure_all(self.main, [self.field, other], cached_only=True)
        self.assertEqual((got["13"]["bytes"], got["13"]["cached"], got["14"]), (first["bytes"], True, None))
        self.assertEqual(cache_file.read_text(), before)

    def test_an_unreadable_cache_is_ignored(self):
        (sizes.store.state_dir(self.main) / sizes.CACHE_FILE).write_text("{broken")
        self.assertFalse(self.measure()["cached"])


if __name__ == "__main__":
    unittest.main()
