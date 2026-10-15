"""Hal2 plan 0313 step 6 (D9, D10): the wagon master's metrics as code (metrics.py). Hermetic: the role folder is
fixtures/metrics/ (train.jsonl, board.jsonl and log.jsonl copied from the real role folder of 2026-10-14, the real
train.jsonl had no landing yet, so its tail adds two synthetic ones: train 06+10 landed at 2026-10-14T10:40Z, train 13
red once then landed on 2026-10-15), and the ci-analyzer is a fake (a function, or a fake main.py for the CLI call);
nothing asks GitHub."""

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import metrics

FIX = Path(__file__).resolve().parent / "fixtures" / "metrics"
UTC = metrics.dt.timezone.utc
SINCE = metrics.parse_time("2026-10-13")  # a day with nothing in it first


def job(created, started, completed, labels=("self-hosted", "hal2-gate"), runner="r1"):
    return {"id": 1, "name": "j", "created_at": created, "started_at": started, "completed_at": completed,
            "runner_name": runner, "labels": list(labels), "conclusion": "success", "status": "completed"}


def run(rid, branch, created, jobs):
    return {"id": rid, "attempt": 1, "head_branch": branch, "created_at": created, "started_at": created,
            "status": "completed", "conclusion": "success", "jobs": jobs}


CI_RUNS = [
    # day 14: a landing run whose first job waited 10 min for the gate runner a check run held, whose second job
    # waited 30 s on another kind of runner, and a skipped job without a runner
    run(1, "land/wagon-master-hal2", "2026-10-14T09:00:00Z",
        [job("2026-10-14T09:00:00Z", "2026-10-14T09:10:00Z", "2026-10-14T09:30:00Z"),
         job("2026-10-14T09:00:00Z", "2026-10-14T09:00:30Z", "2026-10-14T09:05:30Z", labels=("self-hosted", "mac")),
         job("2026-10-14T09:00:00Z", None, None, runner=None)]),
    run(2, "13", "2026-10-14T08:50:00Z", [job("2026-10-14T08:50:00Z", "2026-10-14T08:50:10Z", "2026-10-14T09:15:00Z")]),
    # day 15: a landing run that waited for nothing
    run(3, "land/wagon-master-hal2", "2026-10-15T09:00:00Z",
        [job("2026-10-15T09:00:00Z", "2026-10-15T09:00:00Z", "2026-10-15T09:30:00Z")]),
]


def fake_ci(runs=CI_RUNS):
    return lambda: runs


class FoldTest(unittest.TestCase):
    def setUp(self):
        self.m = metrics.measure(FIX, SINCE, ci=fake_ci())

    def test_landings_and_trains_per_day(self):
        t, d = self.m["total"], self.m["days"]
        self.assertEqual((t["landings"], t["trains"]), (2, 6))
        self.assertEqual(t["trains_per_landing"], 3.0)
        self.assertEqual(list(d), ["2026-10-13", "2026-10-14", "2026-10-15"])
        self.assertEqual([d[k]["landings"] for k in d], [0, 1, 1])
        self.assertEqual([d[k]["trains"] for k in d], [0, 5, 1])
        self.assertIsNone(d["2026-10-13"]["trains_per_landing"])

    def test_first_try_green_rate(self):
        """Day 14: 06+10 landed at once, 06, 07, 06+05+10 and 06+10+07 went red and never landed: 1 of 5. Day 15: train
        13 landed after a red and a retry: not first-try, 0 of 1."""
        t, d = self.m["total"], self.m["days"]
        self.assertEqual(d["2026-10-14"]["first_try_green_rate"], 0.2)
        self.assertEqual(d["2026-10-15"]["first_try_green_rate"], 0.0)
        self.assertEqual(t["first_try_green_rate"], 0.17)
        self.assertIsNone(self.m["days"]["2026-10-13"]["first_try_green_rate"])

    def test_red_cause_mix_of_the_real_reds(self):
        """06 python-lint (the car's old word), 07 push (engine, status error), 07 lua-test (the car's spec), 06+05+10
        (the gate's own bug, engine), 06+10+07 records-check (the car's step file), 13 (the runner)."""
        self.assertEqual(self.m["total"]["red_causes"], {"car": 3, "barn": 0, "engine": 2, "runner": 1, "unknown": 0})
        self.assertEqual(self.m["days"]["2026-10-14"]["red_causes"]["runner"], 0)
        self.assertEqual(self.m["days"]["2026-10-15"]["red_causes"]["runner"], 1)

    def test_cause_of_rules(self):
        c = metrics.cause_of
        self.assertEqual(c("gate_failed", ["x/lint", "cause: barn. main is red too"]), "barn")
        self.assertEqual(c("error", ["git push: rejected"]), "engine")
        self.assertEqual(c("gate_failed", ["x/gate", "not your code: the gate's own bug"]), "engine")
        self.assertEqual(c("gate_failed", ["x/gate", "main is red on this job as well"]), "barn")
        self.assertEqual(c("gate_failed", ["x/test", "the runner ran out of disk"]), "runner")
        self.assertEqual(c("gate_failed", ["x/lint", "names check finds an old word in 06's file"]), "car")
        self.assertEqual(c("gate_failed", ["x/lint"]), "unknown")

    def test_hitch_to_barn_per_car(self):
        """06 hitched again at 08:32:09 (after its unhitch) and 10 at 08:37:03, both in the barn 10:40:00 (127.9 and
        123.0 min); 13 hitched at 08:50 on the 15th, in the barn 09:40 (50 min)."""
        h = self.m["days"]["2026-10-14"]["hitch_to_barn_min"]
        self.assertEqual((h["n"], h["median"], h["p90"]), (2, 125.4, 127.8))
        self.assertEqual(self.m["days"]["2026-10-15"]["hitch_to_barn_min"], {"n": 1, "median": 50.0, "p90": 50.0})
        self.assertEqual(self.m["total"]["hitch_to_barn_min"]["n"], 3)

    def test_hitch_falls_back_to_the_first_train_without_a_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("train.jsonl", "log.jsonl"):
                (Path(tmp) / name).write_text((FIX / name).read_text())
            h = metrics.measure(tmp, ci=fake_ci())["days"]["2026-10-15"]["hitch_to_barn_min"]
        self.assertEqual(h["median"], 40.0)  # formed 09:00, landed 09:40

    def test_log_counts(self):
        t = self.m["total"]
        self.assertEqual((t["restarts"], t["breakups"], t["hand_fixes"]), (1, 4, 2))

    def test_spread(self):
        self.assertEqual(metrics.spread([]), {"n": 0, "median": None, "p90": None})
        self.assertEqual(metrics.spread(list(map(float, range(1, 11)))), {"n": 10, "median": 5.5, "p90": 9.0})


class CiTest(unittest.TestCase):
    def test_runner_minutes_and_queue_wait(self):
        m = metrics.measure(FIX, SINCE, ci=fake_ci())
        d14, d15 = m["days"]["2026-10-14"], m["days"]["2026-10-15"]
        self.assertEqual((d14["runner_minutes"], d14["runner_minutes_per_landing"]), (25.0, 25.0))
        self.assertEqual(d14["queue_wait_min"], {"total": 10.5, "behind_checks": 10.0})
        self.assertEqual((d15["runner_minutes_per_landing"], d15["queue_wait_min"]["total"]), (30.0, 0.0))
        self.assertEqual(m["total"]["runner_minutes_per_landing"], 27.5)
        self.assertIsNone(m["days"]["2026-10-13"]["runner_minutes_per_landing"])
        self.assertEqual(m["ci"]["status"], "ok")

    def test_ci_failing_or_missing_makes_only_its_metrics_unknown(self):
        def boom():
            raise metrics.CiUnknown("no ci-analyzer found")

        for ci in (boom, mock.Mock(side_effect=RuntimeError("bad json"))):
            m = metrics.measure(FIX, ci=ci)
            self.assertEqual(m["ci"]["status"], "unknown")
            self.assertIsNone(m["total"]["runner_minutes_per_landing"])
            self.assertIsNone(m["total"]["queue_wait_min"])
            self.assertEqual(m["total"]["landings"], 2)  # the rest still computed
            self.assertEqual(m["total"]["red_causes"]["engine"], 2)

    def test_ci_cache_that_starts_after_the_window_is_flagged(self):
        since = metrics.parse_time("2026-10-14")
        self.assertTrue(metrics.measure(FIX, since, ci=fake_ci())["ci"]["partial"])
        early = [run(9, "land/x", "2026-10-13T00:00:00Z", [])] + CI_RUNS
        self.assertFalse(metrics.measure(FIX, since, ci=fake_ci(early))["ci"]["partial"])

    def test_fetch_ci_runs_the_analyzer_as_a_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "main.py"
            fake.write_text("import json, sys\nprint(json.dumps({'runs': [{'id': 7, 'argv': sys.argv[1:]}]}))\n")
            with mock.patch.dict(os.environ, {"HAL_CI_ANALYZER": str(fake)}):
                runs = metrics.fetch_ci(Path(tmp), offline=True, runs=5)
            self.assertEqual(runs[0]["argv"], ["fetch", "--json", "--runs", "5", "--offline"])
            fake.write_text("import sys\nsys.exit('boom')\n")
            with mock.patch.dict(os.environ, {"HAL_CI_ANALYZER": str(fake)}), self.assertRaises(metrics.CiUnknown):
                metrics.fetch_ci(Path(tmp))
            fake.write_text("print('not json')\n")
            with mock.patch.dict(os.environ, {"HAL_CI_ANALYZER": str(fake)}), self.assertRaises(metrics.CiUnknown):
                metrics.fetch_ci(Path(tmp))

    def test_fetch_ci_without_an_analyzer(self):
        with mock.patch.object(metrics, "analyzer_for", return_value=None), self.assertRaises(metrics.CiUnknown):
            metrics.fetch_ci(Path("/nonexistent"))


class WindowTest(unittest.TestCase):
    def test_since_and_until(self):
        m = metrics.measure(FIX, metrics.parse_time("2026-10-15"), metrics.parse_time("2026-10-16"), ci=fake_ci())
        self.assertEqual(list(m["days"]), ["2026-10-15"])
        self.assertEqual((m["total"]["landings"], m["total"]["trains"]), (1, 1))
        self.assertEqual(m["total"]["red_causes"]["car"], 0)

    def test_an_empty_window_is_none_not_zero(self):
        m = metrics.measure(FIX, metrics.parse_time("2026-11-01"), metrics.parse_time("2026-11-02"), ci=fake_ci())
        t = m["total"]
        self.assertEqual((t["landings"], t["trains"]), (0, 0))
        self.assertIsNone(t["trains_per_landing"])
        self.assertIsNone(t["first_try_green_rate"])
        self.assertIsNone(t["hitch_to_barn_min"]["median"])

    def test_an_empty_role_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = metrics.measure(tmp, ci=fake_ci([]))
        self.assertEqual((m["total"]["landings"], m["days"]), (0, {}))

    def test_torn_and_timeless_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "train.jsonl").write_text('{"kind": "landed", "train": "a"}\n{"at": "2026-10-14T10:00:00Z", "ki\n'
                                                '{"at": "2026-10-14T10:00:00Z", "kind": "landed", "slot": "x", '
                                                '"train": "a", "cars": []}\n')
            self.assertEqual(metrics.measure(tmp, ci=fake_ci([]))["total"]["landings"], 1)

    def test_a_time_without_a_zone(self):
        """train.jsonl is UTC with Z; the legacy log lines carry this machine's local time."""
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Berlin"
        time.tzset()
        try:
            self.assertEqual(metrics.parse_time("2026-10-14T10:22:50", local=True),
                             metrics.dt.datetime(2026, 10, 14, 8, 22, 50, tzinfo=UTC))
            self.assertEqual(metrics.parse_time("2026-10-14T10:22:50"),
                             metrics.dt.datetime(2026, 10, 14, 10, 22, 50, tzinfo=UTC))
        finally:
            os.environ.pop("TZ") if old is None else os.environ.__setitem__("TZ", old)
            time.tzset()


class CliTest(unittest.TestCase):
    def call(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = metrics.main(["--role", str(FIX), *args], ci=fake_ci())
        return code, out.getvalue()

    def test_json(self):
        code, out = self.call("--json", "--since", "2026-10-14", "--until", "2026-10-15T00:00:00Z")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["total"]["landings"], 1)
        self.assertEqual(data["window"]["since"], "2026-10-14T00:00:00Z")
        self.assertEqual(list(data["days"]), ["2026-10-14"])

    def test_text(self):
        code, out = self.call()
        self.assertEqual(code, 0)
        self.assertIn("total: landings 2, trains 6 (3.0/landing)", out)
        self.assertIn("2026-10-15: landings 1", out)

    def test_text_names_unknown(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            metrics.main(["--role", str(FIX)], ci=mock.Mock(side_effect=metrics.CiUnknown("gone")))
        self.assertIn("runner min/landing unknown", out.getvalue())

    def test_no_role_folder(self):
        with self.assertRaises(SystemExit):
            metrics.main(["--role", "/nonexistent/role"], ci=fake_ci())


if __name__ == "__main__":
    unittest.main()
