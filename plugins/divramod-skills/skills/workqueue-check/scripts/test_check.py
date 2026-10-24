import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check  # noqa: E402
import findings as fx  # noqa: E402
import gather  # noqa: E402


def g(key, runs, wall, cpu=0, peak=None):
    return {"key": key, "runs": runs, "not_ok": 0, "wall_ms_total": wall, "wall_ms_p95": 0, "cpu_ms_total": cpu,
            "peak_bytes_max": peak, "queue_wait_ms_total": 0}


class Findings(unittest.TestCase):
    def test_rise_found_and_ranked(self):
        now = [g("build", 10, 100_000), g("test", 10, 10_000)]
        wide = [g("build", 20, 110_000), g("test", 20, 20_000)]  # build before: 10 runs, 10 000 ms
        f, _ = fx.compare_groups("class", now, wide)
        self.assertEqual([x["what"] for x in f], ["class build: mean wall per run"])
        self.assertEqual(f[0]["pct"], 900)

    def test_thin_and_flat_groups_are_quiet(self):
        f, _ = fx.compare_groups("class", [g("a", 2, 9000)], [g("a", 4, 9100)])
        self.assertEqual(f, [])
        f, _ = fx.compare_groups("class", [g("a", 10, 10_050)], [g("a", 20, 20_000)])
        self.assertEqual(f, [])

    def test_marks_and_bench(self):
        m = fx.marks_findings({"hung": 2, "orphan": 0, "docker_stuck": 0}, {"hung": 4, "orphan": 0, "docker_stuck": 0})
        self.assertEqual(m, [])
        m = fx.marks_findings({"hung": 3}, {"hung": 3})
        self.assertEqual(m[0]["was"], 0)
        b = fx.bench_findings({"benchmarks": [{"name": "a", "slower": True}, {"name": "b", "slower": False}]})
        self.assertEqual(len(b), 1)

    def test_peak_note(self):
        _, notes = fx.compare_groups("class", [g("a", 5, 5000, peak=9)], [g("a", 10, 10000, peak=9)])
        self.assertTrue(any("peak" in n for n in notes))


class Collect(unittest.TestCase):
    def test_missing_cli_is_a_message(self):
        with mock.patch.dict(os.environ, {"HAL2_WORKQUEUE_BIN": ""}), mock.patch("shutil.which", return_value=None):
            res = check.collect("24h", False, 0.25)
            self.assertEqual(check.main(["--no-bench"]), 3)
        self.assertIn("not installed yet", res["missing"][0])

    def test_bad_window(self):
        self.assertEqual(check.main(["--since", "soon"]), 2)

    def test_fake_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "fake"
            fake.write_text(f"""#!{sys.executable}
import json, sys
a = sys.argv[1:]
wide = a[a.index('--since') + 1] == '2880m'
if a[0] == 'stats':
    rows = [{{"key":"build","runs":20 if wide else 10,"not_ok":0,"wall_ms_total":110000 if wide else 100000,
             "wall_ms_p95":0,"cpu_ms_total":0,"peak_bytes_max":None,"queue_wait_ms_total":0}}]
    print(json.dumps({{"groups": rows, "total": rows[0]}}))
else:
    print(json.dumps({{"heads": [], "marks": {{"hung": 2 if wide else 1, "orphan": 0, "docker_stuck": 0}}}}))
""")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            with mock.patch.dict(os.environ, {"HAL2_WORKQUEUE_BIN": str(fake)}):
                res = check.collect("24h", False, 0.25)
        self.assertEqual(res["missing"], [])
        self.assertEqual(res["findings"][0]["kind"], "rose")
        self.assertIn("rose 900%", check.human(res))
        self.assertTrue(json.dumps(res))

    def test_empty_journal_is_a_note(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "fake"
            fake.write_text(f"""#!{sys.executable}
import json
z = {{"key":"all","runs":0,"not_ok":0,"wall_ms_total":0,"wall_ms_p95":0,"cpu_ms_total":0,"peak_bytes_max":None,"queue_wait_ms_total":0}}
print(json.dumps({{"groups": [], "total": z, "heads": [], "marks": {{}}}}))
""")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            with mock.patch.dict(os.environ, {"HAL2_WORKQUEUE_BIN": str(fake)}):
                res = check.collect("24h", False, 0.25)
        self.assertTrue(any("no runs" in n for n in res["notes"]))
        self.assertEqual(res["findings"], [])


class Bench(unittest.TestCase):
    def test_missing_unit(self):
        with mock.patch.object(gather, "bench_main", return_value=None):
            r, why, code = gather.bench_compare()
        self.assertIsNone(r)
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
