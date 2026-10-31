"""The tollman's state files with mixed `at` shapes (hal2 plan 0530, step 3): the farmer's tick died 12 h on
"can't compare offset-naive and offset-aware datetimes" because its files mixed naive local, `+02:00`, `+00:00` and
`Z` times. The tollman's own readers (barn, boss, checks, prune, status, watch, yard, metrics, ...) take every shape,
and a whole round, dry and real, runs over a state folder holding all of them. A naive `at` is LOCAL time (the
farmer, 2026-10-31: Europe/Berlin, never UTC)."""

import datetime as dt
import json
import os
import time
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (puts the farmer skill's scripts on the path)
import barn
import boss
import checks
import checks_tell
import metrics_fold
import mtm_ci
import prune
import roletime
import stack_red
import test_tollman
import train_state
import transplant_mark
import watch
import yard_report
from test_farmer import NOW  # naive local, 2026-10-03 10:20

UTC = dt.timezone.utc
SHAPES = ("2026-10-03T09:52:24", "2026-10-03T09:52:24+02:00", "2026-10-03T07:52:24+00:00", "2026-10-03T07:52:24Z")
INSTANT = dt.datetime(2026, 10, 3, 7, 52, 24, tzinfo=UTC)  # what every shape above means in Berlin (CEST)


class Zone(unittest.TestCase):
    def setUp(self):
        super().setUp()
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Berlin"
        time.tzset()
        self.addCleanup(lambda: (os.environ.pop("TZ") if old is None else os.environ.__setitem__("TZ", old),
                                 time.tzset()))


class Readers(Zone):
    def test_every_shape_is_the_same_instant_to_the_readers(self):
        for shape in SHAPES:
            row = {"at": shape}
            self.assertEqual(boss.when(row), INSTANT, shape)
            self.assertEqual(checks_tell.at(row), INSTANT, shape)
            self.assertEqual(checks.at(row), INSTANT, shape)
            self.assertEqual(metrics_fold.parse_time(shape, local=True), INSTANT, shape)
            self.assertEqual(transplant_mark.when(shape), INSTANT, shape)

    def test_an_unreadable_time_is_long_ago_or_none_never_an_exception(self):
        for bad in (None, "", "not a time", 5):
            self.assertLess(boss.when({"at": bad}), INSTANT)
            self.assertLess(checks_tell.at({"at": bad}), INSTANT)
            self.assertIsNone(transplant_mark.when(bad))
            self.assertEqual(barn.age({"at": bad}, NOW), 0.0)
        with self.assertRaises(ValueError):
            metrics_fold.parse_time("not a time")

    def test_barn_age_takes_every_shape_and_a_naive_now(self):
        now = dt.datetime(2026, 10, 3, 10, 52, 24)  # 08:52:24Z: an hour after the shapes' instant
        for shape in SHAPES:
            self.assertEqual(barn.age({"at": shape}, now), 3600.0, shape)
            self.assertEqual(barn.age({"at": shape}, now.astimezone(UTC)), 3600.0, shape)

    def test_the_stack_red_window_the_yard_day_and_the_phase_take_every_shape(self):
        now = INSTANT + dt.timedelta(hours=1)
        for shape in SHAPES:
            row = {"kind": "landed", "train": "t1", "run": "https://x/actions/runs/11", "at": shape}
            fetched = []
            stack_red.watch("/nowhere", "/nowhere", [row], {}, [], fetch=lambda *a: fetched.append(a) or None, now=now)
            self.assertTrue(fetched, f"{shape}: inside the window the run is looked at")
            fetched.clear()
            stack_red.watch("/nowhere", "/nowhere", [row], {}, [], fetch=lambda *a: fetched.append(a) or None,
                            now=INSTANT + dt.timedelta(days=9))
            self.assertEqual(fetched, [], f"{shape}: past the window it is not")
            home = {"kind": "landed", "train": "t1", "yard": {"pulled": True, "kept": [{"path": "a", "why": "x"}]}, "at": shape}
            self.assertEqual(len(yard_report.settled_actions("/nowhere", [home], {}, now)), 1, shape)
            self.assertEqual(yard_report.settled_actions("/nowhere", [home], {}, INSTANT + dt.timedelta(days=2)), [])
            with mock.patch.object(mtm_ci, "runs_of", lambda *a, **k: []):
                self.assertEqual(watch.local_phase_seconds("/nowhere", {"train": "t", "at": shape}, [], "",
                                                           now=INSTANT + dt.timedelta(seconds=90)), 90.0, shape)

    def test_prune_report_reads_a_log_of_every_shape(self):
        data = {"facts": {"disk": {"free_gb": 500, "used_pct": 10}, "fields": []}, "plan": {}}
        for shape in SHAPES:
            log = [{"key": "prune:disk:2026-10-03T09", "at": shape}]
            ctx = {"now": INSTANT + dt.timedelta(minutes=1), "log": log, "dry": True}
            self.assertEqual([a for a in prune.report("/nowhere", ctx, data) if a["kind"] == "disk"], [], shape)
            ctx["now"] = NOW + dt.timedelta(days=2)  # a naive local now, long after
            self.assertEqual([a["kind"] for a in prune.report("/nowhere", ctx, data) if a["kind"] == "disk"], ["disk"])

    def test_the_metrics_fold_reads_a_mixed_file_sorted(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "log.jsonl"
            f.write_text("".join(json.dumps({"at": s, "kind": "x"}) + "\n" for s in (*SHAPES, "junk")))
            rows = metrics_fold.read(f, local=True)
        self.assertEqual([r["at"] for r in rows], [INSTANT] * 4)

    def test_train_state_and_silent_lines_compare_parsed_times(self):
        since = train_state.utc(NOW)  # Z
        self.assertTrue(since.endswith("Z"))
        self.assertEqual(train_state.utc(INSTANT), "2026-10-03T07:52:24Z")
        self.assertEqual(train_state.utc(INSTANT.replace(tzinfo=None)), "2026-10-03T05:52:24Z")  # a naive time is local


class Rounds(Zone, test_tollman.Rounds):
    """A whole tick over a state folder whose files hold every shape, dry and real."""

    def mixed(self):
        self.wm_state.mkdir(parents=True, exist_ok=True)
        rows = [{"kind": "relay", "slot": "07", "what": "old", "key": f"mixed:{i}", "by": "tick", "do": "relay",
                 "at": shape} for i, shape in enumerate(SHAPES)]
        rows.append({"kind": "relay", "slot": "07", "what": "junk", "key": "mixed:junk", "by": "tick", "at": "no time"})
        (self.wm_state / "log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (self.wm_state / "runs.jsonl").write_text("".join(json.dumps({"at": s, "name": "duty:mtm"}) + "\n"
                                                          for s in SHAPES))
        train = [{"schema": 1, "at": s, "kind": "formed", "slot": "-", "train": f"t{i}", "cars": []}
                 for i, s in enumerate(SHAPES)]
        (self.wm_state / "train.jsonl").write_text("".join(json.dumps(r) + "\n" for r in train))
        (self.wm_state / "board.jsonl").write_text("".join(json.dumps({"at": s, "kind": "ready", "slot": "07"}) + "\n"
                                                           for s in SHAPES))

    def test_a_dry_round_over_a_mixed_state_folder(self):
        self.mixed()
        code, out = self.call("tick", "--dry-run", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["problems"] if "problems" in json.loads(out) else [], [])

    def test_a_real_round_over_a_mixed_state_folder_and_its_status(self):
        self.mixed()
        self.call("mode", "timer")
        code, out = self.call("tick")
        self.assertEqual(code, 0, out)
        written = [e["at"] for e in self.wm_log()][len(SHAPES) + 1:]
        self.assertTrue(written and all(a.endswith("Z") for a in written), written)  # new lines are UTC `Z`
        status = json.loads(self.call("status", "--json", repo=self.main)[1])
        self.assertTrue(status["last_tick"].endswith("Z"), status["last_tick"])
        self.assertGreaterEqual(status["last_tick_age_s"], 0)


for _name in [n for n in dir(Rounds) if n.startswith("test_") and n not in Rounds.__dict__]:
    setattr(Rounds, _name, None)  # only this class's own tests run, not the inherited Rounds tests again


if __name__ == "__main__":
    unittest.main()
