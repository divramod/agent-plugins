"""Hal2 plan 0375 D5: a train's own worktree `tollman-train-<plan>-...` (train_wt.py), its name, and its drop only
through the never-delete-unsaved-work proof; plan 0610 D18: the systematic names (run_names.py, the same as the yard's
roles/tollman/train_names.py) and the kept carrier worktree `tollman-train` on `train-<n>-<a>`. A temporary repository (origin, the yard, the tollman's field), never the
user's; the train's landing is never started."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import importlib.util

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import git_seed
import pretest_train
import run_names
import train_wt

os.environ.setdefault("HAL2_WORKQUEUE_FREEZE", "0")  # no test takes a real workqueue hold (plan 0466)


def git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Name(unittest.TestCase):
    def test_the_cars_plan_numbers_in_order_else_the_field(self):
        cars = [{"field": "07", "plan": "0375-tollman-switch"}, {"field": "09", "plan": "0365-queue-view"},
                {"field": "11", "plan": ""}, {"field": "12", "plan": "tollman/3/a-shot"}]
        self.assertEqual(train_wt.name(cars), "tollman-train-0375-0365-f11-f12")
        self.assertTrue(train_wt.is_train("tollman-train-0375") and not train_wt.is_train("tollman-hal2"))
        self.assertTrue(train_wt.ours(None, "tollman-hal2") and train_wt.ours("tollman-train-f07", "tollman-hal2"))
        self.assertFalse(train_wt.ours("02", "tollman-hal2"), "another field's carrier")

    def test_l104_a_23_car_train_s_name_stays_within_hal2_git_s_64_characters(self):
        cars = [{"field": f"{n:02}", "plan": f"{300 + n:04}-plan"} for n in range(1, 24)]
        self.assertEqual(train_wt.name(cars), "tollman-train-big-0301-0323-23")
        self.assertLessEqual(len(train_wt.name(cars)), train_wt.MAX)
        five = cars[:5]
        self.assertEqual(train_wt.name(five), "tollman-train-0301-0302-0303-0304-0305", "a short name stays whole")
        self.assertEqual(train_wt.name(cars[:20]), "tollman-train-big-0301-0320-20", "the same cars, the same name")


class Repo(unittest.TestCase):
    """The temporary repository every worktree test runs in."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        git_seed.guard(self)
        git_seed.grow(self.tmp, "test_train_wt.Drop", self.grow)
        self.main, fields = self.tmp / "hal2", self.tmp / "worktree"
        self.field, self.car = fields / "tollman-hal2", fields / "07"
        self.cars = [{"field": "07", "plan": "0375-tollman-switch"}]

    def grow(self):
        """The yard, its origin, the tollman's field and 07's, grown once and shared by every process (git_seed)."""
        origin, self.main = self.tmp / "origin.git", self.tmp / "hal2"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.tmp, "clone", "-q", str(origin), str(self.main))
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
            git(self.main, "config", k, v)
        self.commit(self.main, "a.txt")
        git(self.main, "push", "-q", "origin", "HEAD:main")
        fields = self.tmp / "worktree"
        self.field = fields / "tollman-hal2"
        git(self.main, "worktree", "add", "-q", "-b", "tollman-hal2", str(self.field))
        self.car = fields / "07"
        git(self.main, "worktree", "add", "-q", "-b", "07", str(self.car))
        self.commit(self.car, "seven.txt")
        git(self.car, "push", "-q", "origin", "07")

    def commit(self, cwd, name):
        (Path(cwd) / name).write_text(name)
        git(cwd, "add", name)
        git(cwd, "commit", "-qm", name)



class Drop(Repo):
    def train(self) -> Path:
        code, wt = train_wt.add(str(self.field), self.cars)
        self.assertEqual(code, 0, wt)
        git(wt, "merge", "-q", "--no-ff", "-m", "Merge branch '07'", "07")
        return Path(wt)

    def test_a_train_of_merges_is_dropped_with_its_branch(self):
        wt = self.train()
        self.assertEqual((wt.name, wt.parent, git(wt, "branch", "--show-current")),
                         ("tollman-train-0375", self.field.parent, "tollman-train-0375"))
        (wt / "plans").mkdir()
        (wt / "plans/CURRENT_PLAN").write_text("0375-tollman-switch\n")  # the train's title, no car's work
        self.assertEqual(train_wt.drop(str(wt)), (0, "worktree tollman-train-0375 dropped"))
        self.assertEqual((wt.exists(), git(self.main, "branch", "--list", wt.name)), (False, ""))
        self.assertEqual(train_wt.drop(str(wt))[0], 0, "gone already")

    def test_unsaved_work_keeps_the_worktree(self):
        wt = self.train()
        (wt / "a.txt").write_text("changed")
        code, text = train_wt.drop(str(wt))
        self.assertEqual(code, 1)
        self.assertIn("kept (never delete unsaved work): 1 uncommitted change(s)", text)
        git(wt, "commit", "-qam", "a hand's commit")
        code, text = train_wt.drop(str(wt))
        self.assertEqual(code, 1)
        self.assertIn("1 commit(s) of no train and on no other origin branch", text)
        self.assertTrue(wt.is_dir())
        code, text = train_wt.add(str(self.field), self.cars)
        self.assertEqual(code, 1, "the same train's name is taken by unsaved work: no train forms")
        self.assertIn("left from before", text)
        git(wt, "reset", "-q", "--hard", "HEAD^")
        self.assertEqual(train_wt.add(str(self.field), self.cars), (0, str(wt)), "a clean leftover goes first")

    def test_l55_a_landed_train_s_origin_branch_is_deleted_with_a_lease_others_stay(self):
        wt = self.train()
        git(wt, "push", "-q", "origin", f"HEAD:refs/heads/{wt.name}")  # the landing pushes the carrier's head
        git(wt, "push", "-q", "origin", "HEAD:main")  # in the barn
        git(self.main, "fetch", "-q", "origin")
        git(self.field, "switch", "-q", "-c", "tollman-train-0400")  # a train still standing: its local branch
        git(self.field, "push", "-q", "origin", "tollman-train-0400")
        self.commit(self.car, "late.txt")
        git(self.car, "push", "-q", "origin", "HEAD:refs/heads/tollman-train-0401")  # a dead train, not in the barn
        git(self.main, "fetch", "-q", "origin")
        ran = []
        with mock.patch.object(train_wt, "SPAWN", lambda argv, **kw: ran.append(subprocess.run(argv, cwd=kw["cwd"]))):
            code, text = train_wt.drop(str(wt))
        self.assertEqual((code, len(ran), ran[0].returncode), (0, 1, 0), text)
        self.assertIn("origin's landed train branches deleted: tollman-train-0375", text)
        heads = git(self.main, "ls-remote", "--heads", "origin")
        self.assertNotIn("refs/heads/tollman-train-0375", heads)
        for kept in ("tollman-train-0400", "tollman-train-0401", "07"):
            self.assertIn(f"refs/heads/{kept}", heads)
        self.assertEqual(train_wt.sweep(str(self.main)), "", "nothing left to delete: no push")

    def test_only_a_train_s_worktree_is_ever_dropped(self):
        self.assertEqual(train_wt.drop(str(self.car))[0], 1)
        self.assertTrue(self.car.is_dir())
        stray = self.field.parent / "tollman-train-f99"
        stray.mkdir()
        self.assertIn("is no worktree of its own", train_wt.drop(str(stray))[1])

    def test_the_landing_stamps_its_own_pid_on_the_mark(self):
        wt, calls = self.train(), []
        with mock.patch.object(engine, "cli", lambda args, cwd: calls.append(args) or (0, "{}")), \
                mock.patch.object(pretest_train, "before_landing", return_value=True), \
                mock.patch.object(engine.land_name, "refuses", return_value=0), \
                mock.patch("sys.stdout"):
            self.assertEqual(engine.land(str(wt)), 1, "a red pretest starts no landing")
        self.assertEqual(calls[0], ["worktree", "queue", "train", wt.name, "--pid", str(os.getpid()), "--json"],
                         "the sleep stops the train's process group by it (plan 0375 D2)")
        self.assertEqual([c for c in calls[1:] if c != ["worktree", "queue", "--json"]], [],
                         "else only land_name.py's read of the queue (its land branch's name)")


def yard_names():
    """The yard's `roles/tollman/train_names.py` (absent in a published copy of the skill), or None."""
    root = next((p for p in Path(__file__).resolve().parents if (p / "roles/tollman/train_names.py").is_file()), None)
    if not root:
        return None
    spec = importlib.util.spec_from_file_location("yard_train_names", root / "roles/tollman/train_names.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Names(unittest.TestCase):
    """Plan 0610 D18 (roles/tollman/ROLE.md's table): one systematic name per train run, fix and resolve."""

    def test_every_name_of_the_table(self):
        self.assertEqual(run_names.carrier_name(51, 1), "train-51-1")
        self.assertEqual(run_names.fix_name("07", 51, 2), "07-train-51-2-fix")
        self.assertEqual(run_names.fix_name("07", 51, 2, "resolve"), "07-train-51-2-resolve")
        self.assertEqual(run_names.fix_name("main", 51, 2), "tollman-train-51-2-fix", "the tollman's own")
        self.assertEqual((run_names.fix_worktree("07"), run_names.fix_worktree("main")), ("07-fix", "tollman-fix"))
        for bad in (lambda: run_names.fix_name("7", 1, 1), lambda: run_names.fix_name("07", 0, 1),
                    lambda: run_names.fix_name("07", 1, 1, "fix2")):
            self.assertRaises(ValueError, bad)

    def test_a_fix_starts_from_the_run_it_fixes_one_branch_per_field_and_run(self):
        red = {"number": 51, "starts": 2, "state": "fixing"}
        self.assertEqual((run_names.fix_branch(red, "07"), run_names.base_ref(red, "x")),
                         ("07-train-51-2-fix", "train-51-2"), "the second run's red")
        self.assertEqual(run_names.fix_branch({**red, "state": "landing"}, "07"), "07-train-51-2-fix", "early")
        formed = {"number": 52, "starts": 0, "state": "formed"}
        self.assertEqual(run_names.fix_branch(formed, "07", "resolve"), "07-train-52-1-resolve", "the run being formed")
        self.assertEqual(run_names.base_ref({**red, "state": "retry"}, "x"), "train-51-3", "after the fixes: the next")
        old = {"number": None, "starts": 1, "state": "red"}  # formed before plan 0398: the legacy names
        self.assertEqual((run_names.fix_branch(old, "07"), run_names.fix_branch(old, "main"),
                          run_names.fix_branch(old, "07", "resolve"), run_names.base_ref(old, "tollman-train-0294")),
                         ("07-train-fix", "tollman-train-fix", "07-train-resolve", "tollman-train-0294"))

    def test_trains_and_fixes_are_told_apart(self):
        for train in ("tollman-train", "train-51-1", "tollman-train-0375", "tollman-train-big-0301-0323-23"):
            self.assertTrue(train_wt.is_train(train), train)
        for other in ("tollman-train-fix", "tollman-train-51-1-fix", "07-train-51-1-fix", "07-train-51-1-resolve",
                      "tollman-fix", "07-fix", "tollman-hal2", "07", None):
            self.assertFalse(train_wt.is_train(other), other)

    def test_parse_and_off_standard_read_the_systematic_names(self):
        self.assertEqual(run_names.parse("origin/train-7-2"), {"kind": "carrier", "n": 7, "a": 2})
        self.assertEqual(run_names.parse("14-train-7-2-fix"), {"kind": "fix", "n": 7, "a": 2, "field": "14"})
        self.assertEqual(run_names.parse("tollman-train-7-2-resolve")["kind"], "resolve")
        for no in ("train-7", "07-train-fix", "land/train-7-2", "tollman-train", "", None):
            self.assertIsNone(run_names.parse(no), no)
        names = ["train-7-1", "14-fix", "tollman-train", "07-train-fix", "tollman-train-big", "main", "x-resolve"]
        self.assertEqual(run_names.off_standard(names), ["07-train-fix", "tollman-train-big", "x-resolve"])

    def test_the_names_are_the_yard_s_train_names(self):
        yard = yard_names()
        if yard is None:
            self.skipTest("the yard's roles/tollman/train_names.py is not here (a published copy)")
        self.assertEqual(run_names.carrier_name(51, 1), yard.make_carrier(51, 1))
        for field in ("07", "tollman"):
            self.assertEqual(run_names.fix_name(field, 51, 2), yard.make_fix(field, 51, 2))
            self.assertEqual(run_names.fix_name(field, 51, 2, "resolve"), yard.make_resolve(field, 51, 2))
            self.assertEqual(run_names.fix_worktree(field), yard.worktree_of(yard.make_fix(field, 51, 2)))
        self.assertEqual(run_names.KEPT, yard.worktree_of("train-51-1"))


class Kept(Repo):
    """Plan 0610 D18: a numbered train forms in the kept `tollman-train`, its branch `train-<n>-1`; its drop deletes
    only the branch, so the folder's build caches stay warm for the next train."""

    def numbered(self, number: int) -> Path:
        code, wt = train_wt.add(str(self.field), self.cars, number)
        self.assertEqual(code, 0, wt)
        return Path(wt)

    def test_the_next_train_reuses_the_kept_worktree_and_its_cache(self):
        info = Path(self.main) / git(self.main, "rev-parse", "--git-common-dir") / "info"
        info.mkdir(exist_ok=True)
        (info / "exclude").write_text("target/\n")  # a build folder: ignored, never unsaved work
        wt = self.numbered(7)
        self.assertEqual((wt.name, git(wt, "branch", "--show-current")), ("tollman-train", "train-7-1"))
        (wt / "target").mkdir()
        (wt / "target/cache.bin").write_text("warm")
        git(wt, "merge", "-q", "--no-ff", "-m", "Merge branch '07'", "07")
        git(wt, "push", "-q", "origin", "HEAD:refs/heads/train-7-1")  # a fix order's published base
        git(wt, "push", "-q", "origin", "HEAD:main")  # landed
        git(self.main, "fetch", "-q", "origin")
        ran = []
        with mock.patch.object(train_wt, "SPAWN", lambda argv, **kw: ran.append(subprocess.run(argv, cwd=kw["cwd"]))):
            code, text = train_wt.drop(str(wt))
        self.assertEqual(code, 0, text)
        self.assertIn("worktree tollman-train kept for the next train, its branch train-7-1 dropped", text)
        self.assertIn("origin's landed train branches deleted: train-7-1", text)
        self.assertEqual((wt.is_dir(), git(self.main, "branch", "--list", "train-7-1")), (True, ""))
        self.assertEqual(self.numbered(8), wt, "the same folder")
        self.assertEqual((git(wt, "branch", "--show-current"), (wt / "target/cache.bin").read_text()),
                         ("train-8-1", "warm"), "the next train's branch, the cache still warm")
        self.assertEqual(git(wt, "rev-parse", "HEAD"), git(self.field, "rev-parse", "HEAD"), "at the field's head")

    def test_a_broken_up_train_s_run_is_deleted_through_the_proof_a_standing_one_s_stays(self):
        """Plan 0610 step 9: `origin/train-<n>-<a>` of a train broken up (never in the barn) goes once every commit of
        it is a merge or on another origin branch; a hand's commit keeps it, and the standing train's runs stay."""
        wt = self.numbered(5)
        git(wt, "merge", "-q", "--no-ff", "-m", "Merge branch '07'", "07")  # 07's commit is on origin/07
        git(wt, "push", "-q", "origin", "HEAD:refs/heads/train-5-1")
        self.commit(wt, "hand.txt")  # a commit of no train, on no other origin branch
        git(wt, "push", "-q", "origin", "HEAD:refs/heads/train-6-1")
        git(wt, "checkout", "-q", "--detach")
        git(self.main, "branch", "-D", "train-5-1")
        git(self.main, "fetch", "-q", "origin")
        with mock.patch.object(train_wt.train_state, "lines", return_value=[]):
            self.assertEqual(train_wt.landed(str(self.main)), {"train-5-1": git(self.main, "rev-parse", "origin/train-5-1")},
                             "the hand's commit keeps train-6-1")
        formed = {"kind": "formed", "train": "07@x", "slot": "tollman-train", "number": 5, "cars": []}
        with mock.patch.object(train_wt.train_state, "lines", return_value=[formed]):
            self.assertEqual(train_wt.landed(str(self.main)), {}, "train 5 stands: its runs stay")

    def test_unsaved_work_in_the_kept_worktree_forms_no_train_and_keeps_its_branch(self):
        wt = self.numbered(7)
        self.commit(wt, "hand.txt")
        code, text = train_wt.add(str(self.field), self.cars, 8)
        self.assertEqual(code, 1, text)
        self.assertIn("1 commit(s) of no train and on no other origin branch", text)
        self.assertEqual((git(wt, "branch", "--show-current"), git(self.main, "branch", "--list", "train-8-1")),
                         ("train-7-1", ""))

    def test_the_kept_worktree_is_never_a_leftover_and_its_branch_follows_the_run(self):
        wt = self.numbered(7)
        self.assertEqual(train_wt.leftovers(str(self.field), None), [], "never dropped after a barn")
        self.assertEqual(train_wt.to_run(str(wt), 7, 2), (0, "carrier train-7-1 is train-7-2 now"))
        self.assertEqual(git(wt, "branch", "--show-current"), "train-7-2")
        self.assertEqual(train_wt.to_run(str(wt), 7, 2), (0, ""), "named so already")
        legacy = Path(train_wt.add(str(self.field), [{"field": "09", "plan": "0400-x"}])[1])
        self.assertEqual((train_wt.to_run(str(legacy), 7, 3), git(legacy, "branch", "--show-current")),
                         ((0, ""), "tollman-train-0400"), "a plan-named train keeps its name")


if __name__ == "__main__":
    unittest.main()
