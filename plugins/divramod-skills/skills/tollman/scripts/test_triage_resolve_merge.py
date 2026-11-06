"""Hal2 plan 0718 (tollman learning L266, train 56-7 run 42133755939): a red whose culprit commit came onto the carrier
through a resolve or fix merge of a car's field (`fix(0617): resolve 19-resolve-2, field 19's crop onto train-56-5`) is
that car's: `triage.car_files` adds the files of such merges to their car, so the early order goes to the car and
red_orders finds no MISSING job. The replay is the train 56-7 case on engine_farm.py's farm (a real carrier worktree);
a merge that names no car, or two, changes nothing."""
# enforces .adr/deterministic-first.md and .adr/tollman.md

import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import red_orders
import run_names
import train_state
import triage
from engine_farm import Farm, out
from gh_fake import FakeGh, job, run
from test_farmer import git

CULPRIT = "code/rust/apps/hal2-cli-agents/src/kinds.rs"
RESOLVE = "fix(0617): resolve 19-resolve-2, field 19's crop onto train-56-5"  # the subject of 4f2409e666
LOG = f"d1-01-rust-test\ttest\t2026-11-06T01:02:00.1Z error: help lacks `kinds` in {CULPRIT}:3"


class Train56x7(Farm):
    """Train 19+02 lands; its carrier takes `merge(subject)`, which brings CULPRIT in from a side branch."""

    def setUp(self):
        super().setUp()
        self.crop("19", {"code/x/nineteen.py": "19"}, plan="0555-nineteen")
        self.crop("02", {"two.txt": "2"}, plan="0381-two")
        self.panes = {"19": "%19", "02": "%2"}
        self.round()
        self.assertEqual(self.train()["state"], "landing")
        self.alive.add(self.train()["pid"])
        self.run = run(720, "land/" + self.train()["land_ref"], "2099-01-01T00:00:00Z", status="in_progress")
        self.url = self.run["url"]
        self.gh = FakeGh([self.run], jobs={"720": [job("d1-01-rust-test"), job("d1-02-ts-test", None)]},
                         logs={"720": LOG}).start(self)
        queue, fake = mtm_scan.run_json, self.gh.run_json
        p = mock.patch.object(mtm_scan, "run_json", lambda args, cwd=None: fake(args, cwd) if args[:1] == ["gh"]
                              else queue(args, cwd))
        p.start()
        self.addCleanup(p.stop)

    def merge(self, subject, files=(CULPRIT,)):
        """On the carrier: a side branch with `files`, merged with `subject` (the first parent is the carrier line)."""
        carrier = out(self.cw, "branch", "--show-current")
        side = f"side-{abs(hash(subject))}"
        git(self.cw, "switch", "-q", "-c", side, carrier)
        for f in files:
            (self.cw / f).parent.mkdir(parents=True, exist_ok=True)
            (self.cw / f).write_text("kinds")
            git(self.cw, "add", f)
        git(self.cw, "commit", "-qm", "the resolved crop")
        git(self.cw, "switch", "-q", carrier)
        git(self.cw, "merge", "-q", "--no-ff", "-m", subject, side)

    def cars(self):
        return {c["field"]: c["files"] for c in triage.car_files(str(self.main), self.train())}

    def test_the_resolve_merge_s_files_are_its_car_s(self):
        self.merge(RESOLVE)
        cars = self.cars()
        self.assertEqual(cars["19"], ["code/x/nineteen.py", CULPRIT], "the car's own file, then the resolve's")
        self.assertEqual(cars["02"], ["two.txt"])

    def test_train_56_7_orders_car_19_early_and_red_orders_finds_no_missing_job(self):
        self.merge(RESOLVE)
        self.round()
        self.assertIn(("early-order", "run", "19"), self.last)
        self.assertNotIn(("train-red", "wake", "-"), self.last, "one car named: nobody woken")
        o = [e for e in train_state.lines(str(self.main)) if e["kind"] == "order"][-1]
        self.assertEqual(o["field"], "19")
        done = red_orders.check(str(self.main), [self.url], read=lambda rid: self.gh.jobs["720"], entries=lambda rid: {})
        self.assertEqual(done["missing"], 0, done)
        self.assertEqual(done["runs"][0]["reds"][0]["verdict"], "ordered")

    def test_a_fix_merge_of_a_field_counts_for_that_field_s_car(self):
        self.merge("Merge 19-train-56-5-fix into train-56-5 (fix order 19-fix-1)")
        self.assertEqual(self.cars()["19"][-1], CULPRIT)

    def test_without_the_resolve_merge_nobody_is_named_as_before(self):
        self.round()
        self.assertNotIn(("early-order", "run", "19"), self.last)
        self.assertIn(("train-red", "wake", "-"), self.last, "the session judges an unclear culprit")
        self.assertEqual(self.cars()["19"], ["code/x/nineteen.py"])

    def test_a_merge_naming_no_car_or_two_cars_changes_nothing(self):
        for subject in ("Merge branch 'side' into train-56-5", "Merge 19-train-56-5-fix and 02-fix-4 (19-fix-1)",
                        "Merge 07-train-56-5-fix into train-56-5"):  # 07 rides no car here
            self.merge(subject, files=(f"{len(subject)}.txt",))
        self.assertEqual(self.cars(), {"19": ["code/x/nineteen.py"], "02": ["two.txt"]})

    def test_an_unknown_carrier_gives_the_cars_own_files(self):
        self.merge(RESOLVE)
        train = dict(self.train(), head=None, worktree=None)
        self.assertEqual(triage.carrier_head(train), "")
        self.assertEqual({c["field"]: c["files"] for c in triage.car_files(str(self.main), train)},
                         {"19": ["code/x/nineteen.py"], "02": ["two.txt"]})


class MergeField(unittest.TestCase):
    CARS = {"19", "02"}

    def test_the_systematic_names_of_a_resolve_and_a_fix_name_their_field(self):
        for subject, field in (
                (RESOLVE, "19"),
                ("Merge 02-train-3-1-fix into train-3-1 (fix order 02-fix-7)", "02"),
                ("Merge 19-train-3-2-resolve into train-3-2", "19"),
                ("Merge 19-train-resolve into tollman-train", "19"),
                ("Merge 19-fix-3", "19")):
            self.assertEqual(run_names.merge_field(subject, self.CARS), field, subject)

    def test_no_car_two_cars_or_a_field_that_rides_no_car_name_none(self):
        for subject in ("Merge branch '19' into train-3-1", "fix(0617): resolve", "Merge 19-fix-1 and 02-fix-2",
                        "Merge 07-train-3-1-fix into train-3-1", "Merge tollman-train-3-1-fix into train-3-1", "", None):
            self.assertIsNone(run_names.merge_field(subject, self.CARS), subject)


class OnePlainGit(unittest.TestCase):
    """D3: one `git log` per gather, one `git diff` per merge that names a car; nothing else."""

    def test_the_calls(self):
        calls = []

        def fake(repo, *args):
            calls.append(args[0])
            return (0, "a\tfix(0617): resolve 19-resolve-2\nb\tMerge branch 'x'\nc\tMerge 02-fix-1") if args[0] == "log" \
                else (0, "f.txt")

        with mock.patch.object(triage, "git", fake):
            files = triage.merge_files("/m", {"head": "H", "base": "B"}, {"19", "02"})
        self.assertEqual((files, calls), ({"19": ["f.txt"], "02": ["f.txt"]}, ["log", "diff", "diff"]))


if __name__ == "__main__":
    unittest.main()
