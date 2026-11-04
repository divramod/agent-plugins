"""Hal2 plan 0610 step 10 (D18, D24; roles/tollman/ROLE.md, the user, 2026-11-04: "you should both go to the end of train";
"the tollman and the farmer should only go into the train in the first try of a train"): the tollman's and the
farmer's own branches ride every train as its last two cars, merged by `engine.land` right before the push of its
first run only (role_cars.py); a role car that does not merge never holds the train: it is owed, the farmer gets a
board note, it rides the very next train first, and a second leave-out in a row stops that train (D24). On
engine_farm.py's farm, the landing itself a fake that only counts."""

import contextlib
import io
import subprocess
import sys
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import board
import engine
import role_cars
import train_state
import tollman
from engine_farm import ROLE, Farm, out
from test_farmer import git

RUN = "https://github.com/x/actions/runs/9"
ROLE_FILE = tollman.WIRING.role_file


class Base(Farm):
    """Train 1 (car 07) formed and started; the tollman and the farmer commit on their own branches after it formed."""

    def setUp(self):
        super().setUp()
        self.crop("07", {"seven.txt": "7"}, plan="0294-tollman-role")
        self.round()
        self.alive.add(40001)
        self.mark = self.wm.parent / "landed.txt"  # the landing's fake: one line per landing it ran
        land = [sys.executable, "-c", f"open({str(self.mark)!r}, 'a').write('landed\\n')"]
        for p in (mock.patch.object(engine, "LAND", land), mock.patch.object(engine.next_train, "before_push"),
                  mock.patch.object(engine.pretest_train, "before_landing", return_value=False),
                  mock.patch.object(engine.hold, "stops", return_value=0)):
            p.start()
            self.addCleanup(p.stop)

    def land(self):
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            code = engine.land(str(self.cw))
        runs = len(self.mark.read_text().splitlines()) if self.mark.exists() else 0
        return code, [line for line in text.getvalue().splitlines() if line], runs

    def roles(self):
        return [e for e in train_state.lines(str(self.main)) if e["kind"] == "roles"]

    def has(self, sha):
        return git_ok(self.cw, "merge-base", "--is-ancestor", sha, "HEAD")



class RoleCars(Base):
    def test_both_ride_as_the_last_cars_on_the_first_run_only(self):
        self.assertEqual((self.carrier(), out(self.cw, "branch", "--show-current")), ("tollman-train", "train-1-1"),
                         "the kept carrier on its run's branch (D18)")
        self.commit(self.wm, ROLE_FILE, ROLE + "\nThe tollman's own change.\n")  # its field holds only ROLE.md
        self.commit(self.slot, "roles/farmer/note.md", "farmer\n")
        mine, farmer = out(self.wm, "rev-parse", "HEAD"), out(self.slot, "rev-parse", "HEAD")
        code, lines, runs = self.land()
        self.assertEqual((code, runs), (0, 1), lines)
        self.assertEqual(out(self.cw, "log", "--first-parent", "--format=%s", "origin/main..HEAD").splitlines()[:3],
                         ["Merge branch 'farmer-hal2' into train-1-1", "Merge branch 'tollman-hal2' into train-1-1",
                          "Merge branch '07' into train-1-1"], "the tollman's, then the farmer's: after every car")
        self.assertTrue(self.has(mine) and self.has(farmer))
        r = self.roles()
        self.assertEqual((len(r), [m["field"] for m in r[0]["merged"]], r[0].get("out")),
                         (1, ["tollman-hal2", "farmer-hal2"], None))
        self.assertEqual(self.train()["push"]["head"], out(self.cw, "rev-parse", "HEAD"), "pushed with them")
        self.assertIn("role car farmer-hal2", " ".join(lines))

        self.ends({"status": "gate_failed", "run": RUN, "red": [{"name": "linux / rust-test"}]})
        self.round()
        self.assertEqual(self.train()["state"], "red")
        self.commit(self.wm, ROLE_FILE, ROLE + "\nA later change.\n")
        self.commit(self.slot, "roles/farmer/later.md", "later\n")
        later = out(self.slot, "rev-parse", "HEAD"), out(self.wm, "rev-parse", "HEAD")
        git(self.cw, "commit", "-q", "--allow-empty", "-m", "a fix")  # a new head: the red run's fix
        code, lines, runs = self.land()
        self.assertEqual((code, runs), (0, 2), lines)
        self.assertEqual((len(self.roles()), self.has(later[0]), self.has(later[1])), (1, False, False),
                         "a later run of the same train takes no newer head of either role")

    def test_a_role_car_that_does_not_merge_stays_out_and_the_train_lands(self):
        self.commit(self.slot, "seven.txt", "farmer\n")  # conflicts with car 07's seven.txt
        code, lines, runs = self.land()
        self.assertEqual((code, runs), (0, 1), lines)
        r = self.roles()[0]
        self.assertEqual((r["merged"], [o["field"] for o in r["out"]]), ([], ["farmer-hal2"]))
        self.assertIn("does not merge into the train", r["out"][0]["why"])
        self.assertEqual(out(self.cw, "status", "--porcelain", "--untracked-files=no"), "",
                         "the merge undone, the carrier clean")
        self.assertTrue(any("stays out of this train" in line for line in lines), lines)


class Owed(Base):
    """Plan 0610 D24: train 1 (car 07) leaves the farmer's role car out (its seven.txt clashes with 07's), lands, and
    car 09 hitches for train 2."""

    def setUp(self):
        super().setUp()
        self.commit(self.slot, "seven.txt", "farmer\n")
        code, lines, runs = self.land()
        self.assertEqual((code, runs), (0, 1), lines)
        self.ends({"status": "landed", "commit": "c0ffee", "run": RUN}, land=True)

    def notes(self, kind=None):
        board.sync(str(self.main))
        return [n for n in board.lines(str(self.main), "note") if n["to"] == "farmer-hal2"
                and (kind is None or kind in n["text"])]

    def next_train(self):
        self.crop("09", {"nine.txt": "9"}, plan="0384-nine")
        self.round()
        return self.train()

    def test_one_left_out_is_owed_and_noted_to_the_farmer(self):
        (owed,) = role_cars.owed(train_state.lines(str(self.main))).values()
        self.assertEqual((owed["field"], owed["times"]), ("farmer-hal2", 1), "recorded as owed, once in a row")
        (note,) = self.notes()
        for part in ("role car farmer-hal2", "does not merge into the train", "the next train takes it first"):
            self.assertIn(part, note["text"])

    def test_the_owed_car_rides_the_very_next_train_as_its_first_car(self):
        self.commit(self.slot, "seven.txt", "7")  # the farmer took the barn's side: it merges now
        train = self.next_train()
        self.assertEqual(([c["field"] for c in train["cars"]], train["state"]), (["09"], "landing"))
        self.assertEqual(out(self.cw, "log", "--first-parent", "--format=%s", "origin/main..HEAD").splitlines()[-2:],
                         ["Merge branch '09' into train-2-1", "Merge branch 'farmer-hal2' into train-2-1"],
                         "the farmer's car first, right after the barn, before every wagon")
        first = [e for e in self.roles() if e.get("place") == "first"]
        self.assertEqual([m["field"] for m in first[0]["merged"]], ["farmer-hal2"])
        self.assertEqual(role_cars.owed(train_state.lines(str(self.main))), {}, "owed no more")

    def test_left_out_twice_in_a_row_the_train_stops_never_pushes_and_the_farmer_is_told(self):
        train = self.next_train()  # the farmer's seven.txt still clashes with the barn
        self.assertEqual((train["state"], train["stop"]["field"]), ("stopped", "farmer-hal2"))
        self.assertEqual((self.has(out(self.slot, "rev-parse", "HEAD")), self.has(out(self.fields["09"], "rev-parse",
                                                                                         "HEAD"))), (False, False),
                         "no wagon merged behind a stopped role car")
        (note,) = self.notes("stopped")
        self.assertIn("left out a second time in a row", note["text"])
        code, lines, runs = self.land()
        self.assertEqual((code, runs), (1, 1), "a stopped train never pushes")
        self.round()
        self.assertEqual((self.last, self.train()["state"]), ([("roles", "run", "-")], "stopped"))
        self.assertEqual(sum(bool(e.get("out")) for e in self.roles()), 2, "never a third leave-out")

        self.commit(self.slot, "seven.txt", "7")  # the farmer makes it merge
        with contextlib.redirect_stdout(io.StringIO()) as said:  # the round's action (its key waits out its window)
            self.assertEqual(role_cars.main(["retry", "--repo", str(self.cw)]), 0)
        self.assertIn("role car farmer-hal2", said.getvalue())
        self.assertEqual(self.train()["state"], "formed")
        self.round()  # the restart merges the cars it lacks, after the role car
        self.assertEqual(out(self.cw, "log", "--first-parent", "--format=%s", "origin/main..HEAD").splitlines()[-2:],
                         ["Merge branch '09' into train-2-1", "Merge branch 'farmer-hal2' into train-2-1"])
        self.assertEqual(self.train()["state"], "landing")


def git_ok(cwd, *args) -> bool:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True).returncode == 0


if __name__ == "__main__":
    unittest.main()
