"""Hal2 plan 0294 step 6: the train engine in whole rounds, on engine_farm.py's farm: the foremen's fields 07, 09
and 11 hitch, the tollman's tick forms, lands and settles their trains. `hal2-cli-git` is the farm's `Gate`
(the merge queue as data) and no landing is ever started. No timer, no session, no real queue."""

import contextlib
import dataclasses
import io
import json
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import own_fix
import tick
import train_state
import workqueue_hold
import trains
import tollman
from engine_farm import OWN, Farm, out
from test_farmer import git

os.environ.setdefault("HAL2_WORKQUEUE_FREEZE", "0")  # no test takes a real workqueue hold (plan 0466)

SKILL = Path(__file__).resolve().parents[1]


def git_ok(cwd, *args) -> bool:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True).returncode == 0


class Forming(Farm):
    def test_a_dry_run_forms_one_train_from_two_ready_wagons_and_writes_nothing(self):
        self.crop("07", {"seven.txt": "7"}, plan="0294-tollman-role")
        self.crop("09", {"nine.txt": "9"})
        code, text = self.call("train", "--dry-run", "--json", repo=self.main)
        d = json.loads(text)
        self.assertEqual((code, d["field"], d["standing"], d["alone"], d["unhitched"], d["waiting"]),
                         (0, self.carrier(), None, False, [], []))
        self.assertEqual([(c["field"], c["plan"], c["head"]) for c in d["cars"]],
                         [("07", "0294-tollman-role", self.gate.of("07")["ready"]["head"]),
                          ("09", "", self.gate.of("09")["ready"]["head"])])
        code, text = self.call("train", "--dry-run")
        self.assertIn("standing: no train\nnext train: 07 (0294-tollman-role, ", text)
        r = json.loads(self.call("tick", "--dry-run", "--json")[1])
        self.assertEqual([(a["kind"], a["do"]) for a in r["planned"] if a["duty"] == "trains"],
                         [("form", "run"), ("ran", "ran")])
        self.assertEqual((self.gate.calls, self.spawned, self.state(), self.subjects()), ([], [], [], []))
        self.assertFalse((self.wm_state / train_state.FILE).exists())

    def test_a_place_reserved_for_a_field_that_is_not_ready_holds_the_train_back(self):
        """Every landing waits behind such a place (.adr/merge-queue-policy.md rule 2; step 12 saw the carrier's
        wait on the real queue), so no train forms until the field hitches or the place goes."""
        place = self.gate.ticket("11", self.field("11"), reserved={"by": "the user", "since": "2026-10-13T09:00:00Z"})
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        d = json.loads(self.call("train", "--dry-run", "--json", repo=self.main)[1])
        self.assertEqual((d["cars"], [w["field"] for w in d["waiting"]]), ([], ["07", "09"]))
        self.assertIn("the place reserved for field 11 stands in the queue and 11 is not ready", d["waiting"][0]["why"])
        self.round()
        self.assertEqual((self.last, self.gate.calls, self.spawned, self.state()), ([], [], [], []))
        place["pid"] = 4711  # its own landing waits there: a waiter like any other, the train forms behind it
        self.assertIsNone(trains.held_for(self.gate.queue()["queue"], OWN))
        self.gate.tickets.remove(place)
        self.round()
        self.assertEqual((self.last, self.spawned), ([("form", "run", "-")], [self.carrier()]))

    def test_a_round_merges_the_cars_marks_the_train_and_starts_its_landing(self):
        self.crop("07", {"seven.txt": "7"}, plan="0294-tollman-role")
        self.crop("09", {"nine.txt": "9"})
        base = out(self.wm, "rev-parse", "HEAD")
        self.round()
        self.assertEqual(self.last, [("form", "run", "-")])
        self.assertEqual((self.carrier(), out(self.cw, "branch", "--show-current")), ("tollman-train", "train-1-1"),
                         "the kept train worktree beside the tollman's field, on its run's branch (plan 0610 D18)")
        self.assertEqual(self.subjects(), [f"Merge branch '09' into {self.branch()}",
                                           f"Merge branch '07' into {self.branch()}", "nine.txt", "seven.txt"])
        self.assertEqual((out(self.wm, "rev-parse", "HEAD"), (self.wm / "plans/CURRENT_PLAN").exists()), (base, False),
                         "the tollman's field holds no train")
        self.assertEqual((self.cw / "plans/CURRENT_PLAN").read_text(), "0294-tollman-role + 09\n")
        trailers = lambda rev: out(self.cw, "log", "-1", "--format=%(trailers:only,unfold)", rev).splitlines()
        self.assertEqual((trailers("HEAD"), trailers("HEAD^")), (["Worktree: 09"], ["Worktree: 07", "Plan: 0294-tollman-role"]),
                         "each car's merge says where it came from (plan 0355)")
        self.assertEqual(self.gate.calls, [["worktree", "queue", "train", self.carrier(), "07", "09", "--train", "1", "--attempt", "1"]],
                         "marked with the train's number and its start (plan 0398), then started")
        self.assertEqual(self.spawned, [self.carrier()])
        self.assertEqual(self.state(), [("formed", self.carrier()), ("started", self.carrier())])
        t = self.train()
        self.assertEqual((t["state"], t["starts"], t["pid"], t["base"], [c["field"] for c in t["cars"]]),
                         ("landing", 1, 40001, base, ["07", "09"]))
        self.assertEqual((t["number"], t["land_ref"]), (1, "train-1-1"), "its own branch: number and start (plan 0398)")
        self.assertEqual(self.gate.of("07")["ready"]["head"], t["cars"][0]["head"], "a car keeps its ready ticket")

        self.alive.add(40001)  # the landing runs: the tick never waits for it; the field is free of it (plan 0375 D5)
        plain = dataclasses.replace(tollman.WIRING, carries=None)
        self.assertEqual((tick.slot_problem(str(self.wm), tollman.WIRING), tick.slot_problem(str(self.wm), plain)),
                         (None, None))
        self.assertFalse(train_state.carries(str(self.wm)), "the train's worktree carries it, not the field")
        frame = lambda r: [a["kind"] for a in r["planned"] if a["duty"] == "frame"]  # noqa: E731
        r = self.round()
        self.assertEqual((self.last, frame(r)), ([], []), "origin did not move: no merge-from-main (plan 0480 02.02)")
        (self.main / "moved.txt").write_text("m")
        git(self.main, "add", ".")
        git(self.main, "commit", "-qm", "moved")
        git(self.main, "push", "-q", "origin", "HEAD:main")
        r = self.round()
        self.assertEqual((self.last, frame(r)), ([], ["stay-current"]),
                         "the field's own merge-from-main goes on while the train stands, once origin moved")
        d = json.loads(self.call("train", "--dry-run", "--json", repo=self.main)[1])
        self.assertEqual((d["standing"]["state"], d["cars"]), ("landing", []), "its cars are not the next train's")
        self.assertEqual((self.spawned, len(self.gate.calls)), ([self.carrier()], 1))

    def test_a_conflicting_wagon_rides_and_the_train_waits_for_its_resolve(self):
        # Plan 0522 D18: no unhitch; the whole replay is test_resolve.py's.
        self.commit(self.main, "shared.txt", "base\n", push=True)
        git(self.wm, "merge", "-q", "--ff-only", "main")
        self.crop("07", {"shared.txt": "seven\n"})
        self.crop("09", {"shared.txt": "nine\n"})
        self.round()
        self.assertEqual((self.last, self.gate.calls, self.spawned), ([("form", "run", "-")], [], []))
        self.assertEqual((self.train()["state"], [c["field"] for c in self.train()["cars"]]), ("resolving", ["07", "09"]))

    def test_the_alone_rule_and_what_never_rides(self):
        """Plan 0610 D9, D15: the alone car holds nobody; the others form now, it rides alone in the very next train,
        ahead of a later hitch and without the minimum, keeping its ticket and ready mark."""
        self.crop("07", {".github/workflows/merge-to-main.yml": "on: push\n"})
        self.crop("09", {"nine.txt": "9"})
        self.crop("31", {"servant.txt": "s"})
        (Path(self.fields["31"]) / "plans").mkdir(exist_ok=True)  # D16: a servant by its marker, not its number
        (Path(self.fields["31"]) / "plans/LEAD").write_text("07 0383-train-rules 16\n")
        self.gate.ticket("04", self.fields["07"], ready={"at": "2026-10-13T09:00:00Z", "by": "hal2/04",
                                                        "head": out(self.main, "rev-parse", "origin/main")})
        d = json.loads(self.call("train", "--dry-run", "--json")[1])
        self.assertEqual(([c["field"] for c in d["cars"]], d["alone"], d["alone_next"]), (["09"], False, ["07"]))
        self.assertEqual([(w["field"], w["reason"]) for w in d["waiting"]],
                         [("31", "servant"), ("04", "barn"), ("07", "alone")])
        self.assertIn("rides alone in its own train, right after this one: it adds the landing workflow",
                      d["waiting"][2]["why"])
        self.round()
        self.assertEqual(self.last, [("form", "run", "-")],
                         "no unhitch, no message: 31 (servant) and 04 (in the barn) stay hitched (the user, 2026-11-04)")
        self.assertEqual(self.gate.calls[-1],
                         ["worktree", "queue", "train", self.carrier(), "09", "--train", "1", "--attempt", "1"])
        self.assertEqual(train_state.lines(str(self.main))[0]["alone_next"], ["07"], "the formed line owes 07 its train")
        self.assertTrue(all(self.gate.of(f)["ready"] for f in ("07", "31", "04")), "their ready marks stay")
        seven = self.gate.of("07")
        self.ends({"status": "landed", "commit": "c0ffee"}, land=True)
        self.gate.tickets.append(seven)  # the landing took only its cars' tickets
        self.crop("11", {"eleven.txt": "11"})  # hitched after 07
        with mock.patch.object(trains, "MIN_HITCHED", 10):  # the user's minimum: never for the alone car (D15)
            self.round()
        self.assertEqual(self.gate.calls[-1],
                         ["worktree", "queue", "train", self.carrier(), "07", "--train", "2", "--attempt", "1"],
                         "07 rides alone in the very next train, ahead of 11")
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07"])
        self.assertTrue(self.gate.of("11")["ready"], "11 waits, hitched, for the train after 07")

    def test_a_car_whose_plan_depends_on_another_rides(self):
        """Plan 0610 E27, D18, D20: no dependency hold (train_depends.py is not built): both ride, in queue order."""
        self.crop("09", {"nine.txt": "9"}, plan="0602-needs-seven")
        (self.fields["09"] / "plans/0602-needs-seven").mkdir(parents=True)
        (self.fields["09"] / "plans/0602-needs-seven/plan.md").write_text("Depends on: 0601-seven\n")
        self.crop("07", {"seven.txt": "7"}, plan="0601-seven")
        self.round()
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["09", "07"])

    def test_a_refused_mark_leaves_the_train_standing_and_the_next_round_lands_it(self):
        """Plan 0610 E25: nothing undoes a forming; the refused mark's train is `formed`, its restart marks it again."""
        self.crop("07", {"seven.txt": "7"})
        head = self.gate.of("07")["ready"]["head"]
        self.gate.refuse = "07"  # the mark with this car
        code, text = engine.form(str(self.wm), [{"field": "07", "branch": "07", "head": head, "plan": ""}])
        self.assertEqual(code, 1, text)
        self.assertIn("was not marked: refused: 07", text)
        self.assertEqual((self.state(), self.train()["state"], self.spawned),
                         ([("formed", self.carrier()), ("attempt", self.carrier())], "formed", []),
                         "a try that started nothing raises the attempt (plan 0620 D5)")
        self.assertEqual(engine.form(str(self.wm), [])[0], 0, "a train stands: no second one")
        self.gate.refuse = ""
        r = self.round()
        self.assertEqual((self.last, r["wake"], self.train()["state"]), ([("restart", "run", "-")], [], "landing"))

    def test_a_car_that_does_not_merge_gets_a_resolve_order_and_the_train_stands(self):
        """Plan 0610 E25: a car whose merge fails in `form` (an untried trial, E15) waits `resolving` with its resolve
        order; the cars before it are merged, nothing is cleared, every ready mark stays."""
        self.commit(self.main, "shared.txt", "base\n", push=True)
        git(self.wm, "merge", "-q", "--ff-only", "main")
        cars = [{"field": f, "branch": f, "head": self.crop(f, {"shared.txt": f + "\n"})["ready"]["head"], "plan": ""}
                for f in ("07", "09")]
        code, text = engine.form(str(self.wm), cars)
        self.assertEqual(code, 0, text)
        self.assertIn("resolve order 09-resolve-1", text)
        t = self.train()
        self.assertEqual((t["state"], t["resolve"]["field"], self.subjects()[0]),
                         ("resolving", "09", f"Merge branch '07' into {self.branch()}"))
        self.assertNotIn("cleared", [k for k, _ in self.state()])
        self.assertTrue(self.gate.of("07")["ready"] and self.gate.of("09")["ready"])

    def test_a_failed_regenerate_leaves_the_train_standing(self):
        """Plan 0610 E25: the generated files not written again: the train stands `formed`, never cleared."""
        self.crop("07", {"seven.txt": "7"})
        car = {"field": "07", "branch": "07", "head": self.gate.of("07")["ready"]["head"], "plan": ""}
        merge = engine.frozen.merge_car
        with mock.patch.object(engine.frozen, "merge_car", lambda *a: (*merge(*a)[:2], ["code/gen.md"])), \
                mock.patch("generated.regenerate", return_value=(1, "the generated files were not written again: x",
                                                                 None, [])):
            code, text = engine.form(str(self.wm), [car])
        self.assertEqual(code, 1, text)
        self.assertIn("stands", text)
        self.assertEqual((self.train()["state"], [k for k, _ in self.state()]), ("formed", ["formed", "regenerated"]))

    def test_a_barn_that_does_not_merge_into_the_field_forms_the_train_on_the_barn(self):
        """Plan 0610 E25: the tollman's own commits clash with the barn: the train forms on the barn's head, its cars
        all ride; the field's commits wait for a later train."""
        self.commit(self.wm, "own.txt", "tollman\n")
        self.commit(self.main, "own.txt", "barn\n", push=True)
        self.crop("07", {"seven.txt": "7"})
        car = {"field": "07", "branch": "07", "head": self.gate.of("07")["ready"]["head"], "plan": ""}
        code, text = engine.form(str(self.wm), [car])
        self.assertEqual(code, 0, text)
        self.assertIn("does not merge into tollman-hal2: the train forms on the barn's head", text)
        self.assertEqual((self.train()["base"], self.train()["state"]),
                         (out(self.main, "rev-parse", "origin/main"), "landing"))
        self.assertEqual(self.subjects(), [f"Merge branch '07' into {self.branch()}", "seven.txt"])


class Minimum(Farm):
    """Plan 0610 D11, D15 (the user, 2026-10-31: "I said at least 10 hitched fields ... So it should be 10 plus."):
    a train forms once MIN_HITCHED fields are hitched and takes every one; the alone car is never bound by it."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(trains, "MIN_HITCHED", 3)
        p.start()
        self.addCleanup(p.stop)

    def test_fewer_wait_hitched_and_the_minimum_takes_every_one(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        self.round()
        self.assertEqual((self.last, self.train()), ([], None))
        d = json.loads(self.call("train", "--dry-run", "--json")[1])
        self.assertEqual([(w["field"], w["reason"], w["why"][:21]) for w in d["waiting"]],
                         [("07", "minimum", "2 of 3 fields hitched"), ("09", "minimum", "2 of 3 fields hitched")])
        self.assertEqual(trains.draft(str(self.main), self.gate.queue()["queue"], OWN, "origin/main", "origin/main",
                                      minimum=0)["cars"][0]["field"], "07", "a join (open_train) has no minimum")
        self.crop("11", {"eleven.txt": "11"})
        self.round()
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07", "09", "11"])

    def test_the_barn_s_own_fix_forms_at_once_below_the_minimum(self):  # plan 0610 D22: a red barn holds every train
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        main = str(self.main)
        train_state.append(main, "order", OWN, field="main", branch="tollman-train-fix", base="b" * 40, why="barn red",
                           id="main-fix-1")
        train_state.append(main, "fixed", OWN, id="main-fix-1", sha="f" * 40)
        self.assertIsNotNone(own_fix.waiting(train_state.lines(main)), "the fix is merged and waits to ride")
        self.round()
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07", "09"], "2 of 3 hitched, yet it forms")

    def test_an_alone_car_below_the_minimum_rides_alone_at_once(self):
        self.crop("07", {".github/workflows/merge-to-main.yml": "on: push\n"})
        self.crop("09", {"nine.txt": "9"})
        self.round()
        self.assertEqual(([c["field"] for c in self.train()["cars"]], self.train()["state"]), (["07"], "landing"))
        self.assertTrue(self.gate.of("09")["ready"], "09 waits, hitched")


class Standing(Farm):
    def setUp(self):
        super().setUp()
        self.crop("07", {"seven.txt": "7"}, plan="0294-tollman-role")
        self.crop("09", {"nine.txt": "9"})
        self.base = out(self.wm, "rev-parse", "HEAD")
        self.round()
        self.alive.add(40001)
        self.assertEqual(self.train()["state"], "landing")

    def test_landed_tells_every_foreman_in_the_barn_and_the_field_is_the_barn_again(self):
        self.panes = {"07": "%7", "09": "%9"}
        self.ends({"status": "landed", "commit": "c0ffee", "run": "https://github.com/x/runs/9"}, land=True)
        self.round()
        self.assertEqual(self.last, [("landed", "run", "-"), ("in-the-barn", "send", "07"), ("in-the-barn", "send", "09"),
                                     ("chain", "run", "-")])
        self.assertEqual([e["what"] for e in self.wm_log() if e["kind"] == "chain"],
                         ["chain link 1: nothing; stops: nothing to do", "the next train in the same round"],
                         "no wagon is ready: the chain's one link, then the round's chain run itself")
        self.assertEqual([p for p, _ in self.typed], ["%7", "%9"])
        self.assertIn("your crop is in the barn (the train of 07, 09, https://github.com/x/runs/9)", self.typed[0][1])
        self.assertEqual((self.train(), self.subjects(), (self.wm / "plans/CURRENT_PLAN").exists()), (None, [], False))
        self.assertEqual((self.cw.exists(), self.branch()), (True, "train-1-1"), "in the barn: the kept worktree "
                         "stays on the landed branch until the next train checks out its own (plan 0610 D18)")
        last = train_state.lines(str(self.main))[-1]
        self.assertEqual((last["kind"], last["cars"], last["run"], last["commit"]),
                         ("landed", ["07", "09"], "https://github.com/x/runs/9", "c0ffee"))
        self.assertIsNone(tick.slot_problem(str(self.wm), tollman.WIRING), "between trains: the frame's own check")
        r = self.round()
        self.assertEqual((self.last, [a["kind"] for a in r["planned"] if a["duty"] == "frame"]), ([], ["stay-current"]))
        self.assertEqual(len(self.typed), 2, "nobody is told twice")

    def test_red_wakes_the_session_once_and_the_user_s_unhitch_lets_the_rest_form_again(self):
        self.ends({"status": "gate_failed", "run": "https://github.com/x/runs/9", "red": [{"name": "linux / rust-test"}]})
        self.gate.of(self.carrier()).update(state="held", train=None, hold={"reason": "failed"})  # the landing's end
        r = self.round()
        self.assertEqual(self.last, [("red", "run", "-"), ("train-failed", "wake", "-")])
        (wake,) = r["wake"]
        for part in ("did not land (gate_failed): linux / rust-test", "Run: https://github.com/x/runs/9.",
                     "Cars: 07 (0294-tollman-role), 09 (09)."):
            self.assertIn(part, wake["text"])
        self.assertEqual(self.call("act")[1].count(str(SKILL / "instructions/trains.md")), 1)
        self.round()
        self.assertEqual((self.last, self.train()["state"], self.spawned), ([], "red", [self.carrier()]), "nothing else")

        # 2026-10-14: unhitched at 12:53:36, broken up by the next round at 12:57:10 (plan 0333 step 6, cause C);
        # now the unhitch's own call breaks the train up, tells 09's foreman and forms the rest; since plan 0360 D3
        # only the user's own unhitch (`--by-user`) takes a car out of the frozen train (class Frozen).
        self.panes = {"09": "%9"}
        code, text = self.call("unhitch", "09", "--why", "its test fails", "--by-user",
                               "--words", "the user said so", repo=self.main)
        self.assertEqual((code, text), (0, "09 unhitched: its test fails; the rest of the train forms again\n"
                                           "chain link 1: breakup -, unhitched 09, form -\n"
                                           "chain stops: a landing started\n"))
        self.assertIsNone(self.gate.of("09"))
        self.assertIn("field 09 is out of the red train by the user's own command: its test fails. Fix it on "
                      "your branch `09`", self.typed[0][1])
        self.assertIn("tell the farmer by SendMessage", self.typed[0][1], "plan 0610 D21: the answer reaches someone")
        self.assertNotIn("done fixed", self.typed[0][1], "no fix order stands after the user's split")
        old = new = "tollman-train"  # one kept carrier worktree, a branch per train and run (plan 0610 D18)
        self.assertIn(["worktree", "release", old, "--by", "the user"], self.gate.calls, "its own failed landing's hold, by the user")
        self.assertEqual((self.carrier(), self.gate.calls[-1]), (new, ["worktree", "queue", "train", new, "07", "--train", "2", "--attempt", "1"]))
        self.assertEqual((self.branch(), git_ok(self.main, "rev-parse", "-q", "--verify", "refs/heads/train-1-1")),
                         ("train-2-1", False), "the broken train's branch dropped, its folder kept (plan 0610 D18)")
        self.assertEqual(self.subjects(), ["Merge branch '07' into train-2-1", "seven.txt"])
        self.assertEqual(self.state()[-5:], [("red", old), ("unhitched", "09"), ("cleared", old), ("formed", new),
                                             ("started", new)])
        self.assertEqual((self.train()["base"], len(self.spawned)), (self.base, 2))
        self.assertEqual([e["what"] for e in self.wm_log() if e["kind"] == "chain"],
                         ["chain link 1: breakup -, unhitched 09, form -; stops: a landing started"])
        self.alive.add(40002)
        self.round()
        self.assertEqual((self.last, len(self.typed), len(self.spawned)), ([], 1, 2), "nothing is done twice")

    def test_a_landed_train_s_round_forms_the_next_train(self):
        # 2026-10-14: landed at 14:07:11, the next train formed by the next round at 14:12:34 (plan 0333 step 6,
        # cause C); now the round that finds the train landed forms the next one.
        self.ends({"status": "landed", "commit": "c0ffee", "run": "https://github.com/x/runs/9"}, land=True)
        self.crop("11", {"eleven.txt": "11"})  # hitched while the train of 07 and 09 landed
        self.round()
        self.assertEqual(self.last, [("landed", "run", "-"), ("in-the-barn", "relay", "07"),
                                     ("in-the-barn", "relay", "09"), ("chain", "run", "-")])
        self.assertEqual(self.state()[-3:], [("landed", "tollman-train"), ("formed", self.carrier()),
                                             ("started", self.carrier())])
        self.assertEqual(self.branch(), "train-2-1", "the kept worktree on the next train's branch (plan 0610 D18)")
        self.assertEqual((self.gate.calls[-1], len(self.spawned)), (["worktree", "queue", "train", self.carrier(), "11", "--train", "2", "--attempt", "1"], 2))
        self.assertEqual(([c["field"] for c in self.train()["cars"]], self.subjects()),
                         (["11"], [f"Merge branch '11' into {self.branch()}", "eleven.txt"]))
        self.assertEqual([e["what"] for e in self.wm_log() if e["kind"] == "chain" and e["do"] == "record"],
                         ["chain link 1: form -; stops: a landing started"])
        self.alive.add(40002)
        self.round()
        self.assertEqual((self.last, len(self.spawned)), ([], 2), "the next round finds its landing running")

    def test_retry_lands_a_red_train_again_as_it_is(self):
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 1, "no red train yet")
        code, text = self.call("unhitch", "09", "--why", "x")
        self.assertEqual(code, 1)
        self.assertIn("a running landing is never stopped", text)
        self.assertTrue(self.gate.of("09"))
        self.ends({"status": "gate_failed", "message": "red"})
        self.round()
        head = out(self.cw, "rev-parse", "HEAD")
        self.assertEqual(self.call("retry", "--why", "flaky: tmux_attach")[0], 0)
        self.round()
        self.assertEqual((self.last, self.train()["state"], self.train()["starts"]), ([("restart", "run", "-")], "landing", 2))
        self.assertEqual((out(self.cw, "rev-parse", "HEAD^"), len(self.spawned)), (head, 2),
                         "the train as it is, one empty commit on it: a new candidate, a fresh run (plan 0313 step 13)")
        self.assertEqual(out(self.cw, "log", "-1", "--format=%B").splitlines()[0],
                         "chore(wagon-train): land the train again on a fresh run (retry 1)")
        self.assertEqual(out(self.cw, "log", "-1", "--format=%(trailers:only,unfold)").splitlines(),
                         ["Worktree: 07, 09"], "a conventional subject, the cars in a trailer (plan 0355)")
        self.assertEqual(self.gate.calls[-1], ["worktree", "queue", "train", self.carrier(), "07", "09", "--train", "1", "--attempt", "2"],
                         "marked before every start, the attempt counting the starts")
        self.assertEqual(self.train()["land_ref"], "train-1-2")

    def test_a_restart_red_on_a_car_s_light_checks_raises_the_attempt_and_the_fixed_train_restarts(self):
        """Plan 0620 D5 (L254, train 53): the restart goes red (proof_red) before its start, so `starts` stays; its
        `attempt` line keys the next round anew, and once the car is fixed that round restarts the train. The car's
        light checks turn red after the round's plan (D6's `pending` saw none, else it orders the car first), so the
        restart's own `red_line` catches it."""
        self.ends({"status": "gate_failed", "message": "red"})
        self.round()
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 0)
        name = self.train()["train"]
        self.assertEqual(train_state.restart_key(self.train()), f"retry:{name}:1")
        with mock.patch.object(engine.proof_orders, "red_cars",
                               lambda train: [dict(train["cars"][1], proof_red=["names: nine.txt"])]), \
                mock.patch.object(engine.proof_orders, "pending", lambda *a: []):
            self.round()
        t = self.train()
        self.assertEqual((self.last, t["state"], t["status"], t["starts"], t["attempt"], len(self.spawned)),
                         ([("restart", "run", "-")], "red", "proof_red", 1, 2, 1), "no start, the attempt raised")
        self.assertEqual(self.state()[-2:], [("red", self.carrier()), ("attempt", self.carrier())])
        main = str(self.main)
        train_state.append(main, "order", self.carrier(), train=name, field="09", branch="09-train-fix",
                           base=t["base"], why="proof", id="09-fix-1")
        train_state.append(main, "fixed", self.carrier(), train=name, field="09", id="09-fix-1", sha="f" * 40,
                           commit=out(self.cw, "rev-parse", "HEAD"))
        self.assertEqual(train_state.restart_key(self.train()), f"retry:{name}:2", "never the used key :1")
        self.round()
        t = self.train()
        self.assertEqual((self.last, t["state"], t["starts"], t["attempt"], len(self.spawned)),
                         ([("restart", "run", "-")], "landing", 2, 3, 2), "the next round restarts the fixed train")

    def test_a_refused_mark_raises_the_attempt_too(self):
        """Plan 0620 D5: a restart past its checks that starts nothing (its mark refused) keys its next try anew."""
        self.ends(None)
        before = self.train()["attempt"]
        with mock.patch.object(engine, "cli", lambda args, cwd: (1, "refused")):
            code, text = engine.restart(str(self.wm))
        self.assertEqual((code, self.train()["attempt"], self.train()["starts"]), (1, before + 1, 1), text)

    def test_an_interrupted_landing_is_started_again_and_adopts_its_run(self):
        self.ends(None)  # the process gone without a word
        self.round()
        self.assertEqual((self.last, self.train()["starts"], self.spawned), ([("restart", "run", "-")], 2, [self.carrier()] * 2))
        self.alive.add(40002)
        self.round()
        self.assertEqual(self.last, [])
        self.ends({"status": "interrupted", "message": "the process that started merge-to-main is gone"})
        self.round()
        self.assertEqual((self.last, self.train()["starts"]), ([("restart", "run", "-")], 3))
        self.assertEqual([k for k, _ in self.state()], ["formed", "started", "started", "started"])

    def test_a_leftover_mark_is_cleared_and_the_round_starts_from_the_ready_tickets(self):
        self.alive.clear()
        left = self.cw.name  # the tollman's state is gone: its train's worktree is left, with the mark
        (self.wm_state / train_state.FILE).unlink()
        self.gate.calls.clear()
        self.round()
        self.assertEqual(self.last, [("breakup", "run", "-"), ("form", "run", "-")])
        self.assertEqual(self.gate.calls, [["worktree", "queue", "train", left, "--clear"],
                                           ["worktree", "queue", "train", left, "07", "09", "--train", "2", "--attempt", "1"]])
        self.assertEqual(self.state(), [("cleared", left), ("formed", left), ("started", left)])
        self.assertEqual(self.subjects(), ["Merge branch '09' into train-2-1", "Merge branch '07' into train-2-1",
                                           "nine.txt", "seven.txt"], "dropped through the proof and formed again, the same cars")
        self.assertEqual(train_state.lines(str(self.main))[0]["why"], "a mark without a train of ours")


class Frozen(Farm):
    """Hal2 plan 0360 D3, D7: nothing leaves a formed train. 2026-10-14 (plan 0333 step 6): the session unhitched
    09 from the red train at 12:53:36 and the train was broken up and formed again without it; now the session's
    unhitch and breakup are refused, only the user's own command (`--by-user`) takes a car out."""

    def setUp(self):
        super().setUp()
        self.crop("07", {"seven.txt": "7"}, plan="0294-tollman-role")
        self.crop("09", {"nine.txt": "9"})
        self.base = out(self.wm, "rev-parse", "HEAD")

    def red(self):
        self.round()
        self.ends({"status": "gate_failed", "run": "https://github.com/x/runs/9", "red": [{"name": "linux / rust-test"}]})
        self.gate.of(self.carrier()).update(state="held", train=None, hold={"reason": "failed"})
        self.round()
        self.assertEqual(self.train()["state"], "red")

    def test_the_session_s_unhitch_and_breakup_of_a_red_train_are_refused(self):
        self.red()
        head, states = out(self.cw, "rev-parse", "HEAD"), self.state()
        code, text = self.call("unhitch", "09", "--why", "its test fails", repo=self.main)
        self.assertEqual(code, 1, text)
        self.assertIn("frozen (plan 0360 D3)", text)
        code, text = self.call("unhitch", "yard", "--why", "x", repo=self.main)
        self.assertEqual(code, 1, "the yard rode nothing here: " + text)
        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet):
            self.assertEqual(engine.main(["breakup", "--why", "the barn is red", "--repo", str(self.wm)]), 1)
        self.assertIn("frozen (plan 0360 D3)", quiet.getvalue())
        self.round()
        self.assertEqual((self.last, self.state(), out(self.cw, "rev-parse", "HEAD"), self.train()["state"]),
                         ([], states, head, "red"), "the train stands as it was")
        self.assertTrue(self.gate.of("09")["ready"], "09 still rides it")

    def test_the_user_s_own_unhitch_still_breaks_a_red_train_up(self):
        self.red()
        code, text = self.call("unhitch", "09", "--why", "the user's word", "--by-user",
                               "--words", "the user said so", repo=self.main)
        self.assertEqual(code, 0, text)
        self.assertIn("chain link 1: breakup -, unhitched 09, form -", text)
        self.assertEqual(self.state()[-4:], [("unhitched", "09"), ("cleared", "tollman-train"),
                                             ("formed", "tollman-train"), ("started", "tollman-train")])
        self.assertEqual(train_state.lines(str(self.main))[-4]["by"], "user")
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07"])

    def test_a_fixing_train_is_frozen_as_a_red_one(self):
        """Plan 0360 step 6: with a fix order open the session's unhitch, breakup and retry are refused as for a red
        train; the user's own unhitch still takes a car out."""
        self.red()
        self.assertEqual(self.call("order", "07", "--why", "its test fails")[0], 0)
        self.assertEqual(self.train()["state"], "fixing")
        code, text = self.call("unhitch", "09", "--why", "x", repo=self.main)
        self.assertEqual(code, 1)
        self.assertIn("frozen (plan 0360 D3)", text)
        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet):
            self.assertEqual(engine.main(["breakup", "--why", "x", "--repo", str(self.wm)]), 1)
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 1)
        self.round()
        self.assertEqual((self.last, self.train()["state"]), ([], "fixing"))
        code, text = self.call("unhitch", "09", "--why", "the user's word", "--by-user",
                               "--words", "the user said so", repo=self.main)
        self.assertEqual(code, 0, text)
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07"])

    def test_a_train_whose_form_died_resumes_with_its_own_cars(self):
        """A `formed` line and only the first car merged (the form's process gone): the same train, its missing car
        merged, marked and started; 11, hitched meanwhile, joins it before its start (plan 0610 D17, E4)."""
        cars = [{"field": f, "branch": f, "head": self.gate.of(f)["ready"]["head"], "plan": ""} for f in ("07", "09")]
        train_state.append(str(self.main), "formed", OWN, train="07+09@x", cars=cars, base=self.base)
        git(self.wm, "merge", "-q", "--no-ff", "-m", f"Merge branch '07' into {self.branch()}", cars[0]["head"])
        self.crop("11", {"eleven.txt": "11"})
        self.round()
        self.assertEqual((self.last, self.state()), ([("join", "run", "-"), ("restart", "run", "-")], [
            ("formed", self.carrier()), ("joined", self.carrier()), ("started", self.carrier())]))
        self.assertEqual(self.gate.calls[-1], ["worktree", "queue", "train", self.carrier(), "07", "09", "11"])
        self.assertEqual([m for m in self.subjects() if m.startswith("Merge")],
                         [f"Merge branch '{f}' into {self.branch()}" for f in ("11", "09", "07")],
                         "the missing car and the joiner merged after the one its form had merged")
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07", "09", "11"])


class UnchangedHead(Farm):
    """Hal2 plan 0560 step 3 (D5, tollman learning L200): train 37's landing died, its restart pushed the unchanged
    candidate on a new land branch and the same 8 reds came again. `engine.land`, the last point before every push,
    refuses the head of the train's last red run; a new head (a retry's empty commit, a fix's merge) lands."""

    RUN = "https://github.com/x/actions/runs/9"

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
        """engine.land in the carrier: (its exit, what it printed, how many landings ran so far)."""
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            code = engine.land(str(self.cw))
        runs = len(self.mark.read_text().splitlines()) if self.mark.exists() else 0
        return code, [line for line in text.getvalue().splitlines() if line], runs

    def test_the_head_of_the_last_red_run_is_refused_a_new_head_lands(self):
        head = out(self.cw, "rev-parse", "HEAD")
        self.assertEqual(self.land()[0::2], (0, 1))
        push = train_state.lines(str(self.main))[-1]
        self.assertEqual((push["kind"], push["slot"], push["train"], push["head"]),
                         ("push", self.carrier(), self.train()["train"], head))
        self.ends({"status": "gate_failed", "run": self.RUN, "red": [{"name": "linux / rust-test"}]})
        self.round()
        red = train_state.lines(str(self.main))[-1]
        self.assertEqual((red["kind"], red["head"], self.train()["push"]),
                         ("red", head, {"head": head, "run": self.RUN, "red": True}))
        code, lines, runs = self.land()  # a path into the push that does not change the candidate (L200's restart)
        self.assertEqual((code, runs), (1, 1), "refused: no landing ran")
        self.assertEqual(lines[0], f"tollman: refused: train 1's candidate {head[:12]} is the head of its last red run "
                                   f"{self.RUN}; waiting for a fix")
        self.assertEqual(json.loads(lines[1])["status"], "refused", "its result: the round records the red at once")
        self.assertEqual(train_state.lines(str(self.main))[-1]["kind"], "red", "no push line")
        git(self.cw, "commit", "-q", "--allow-empty", "-m", "a fix")  # a new head: a retry's empty commit, a fix
        self.assertEqual(self.land()[0::2], (0, 2))
        self.assertEqual(self.train()["push"], {"head": out(self.cw, "rev-parse", "HEAD"), "run": None, "red": False})

    def test_a_died_landing_s_red_run_on_github_is_refused_too(self):
        """L200: no `red` line, the landing died; its run (noted by watch.py) ended red on GitHub. A cancelled run
        (a smuggle's pause) is no red: the same head lands again."""
        main, name = str(self.main), self.train()["train"]
        self.assertEqual(self.land()[0::2], (0, 1))
        train_state.append(main, "run", self.carrier(), train=name, run=self.RUN)  # watch.py noted it, then it died
        cancelled = [{"databaseId": 9, "status": "completed", "conclusion": "cancelled"}]
        with mock.patch.object(engine.head_guard.mtm_ci, "runs_of", return_value=cancelled):
            self.assertEqual(self.land()[0::2], (0, 2), "a cancelled run is no red")
        train_state.append(main, "run", self.carrier(), train=name, run=self.RUN)
        failed = [{"databaseId": 9, "status": "completed", "conclusion": "failure"}]
        with mock.patch.object(engine.head_guard.mtm_ci, "runs_of", return_value=failed):
            code, lines, runs = self.land()
        self.assertEqual((code, runs, lines[0].split(" is the head")[0]),
                         (1, 2, f"tollman: refused: train 1's candidate {out(self.cw, 'rev-parse', 'HEAD')[:12]}"))
        self.ends(json.loads(lines[1]))  # its result: the round records the red at once, never a restart
        self.round()
        red = train_state.lines(str(self.main))[-1]
        self.assertEqual((self.last[0], red["kind"], red["status"], red["run"], self.train()["starts"]),
                         (("red", "run", "-"), "red", "refused", self.RUN, 1))


def check_problems(case, p):
    """The problems of a failed `hal2-cli-roles check`: the error document's details on stderr (plan 0318 step 10), else
    the report on stdout; an installed CLI that predates that contract (CI's) skips the test with the reason."""
    for text, pick in ((p.stderr, lambda d: d["error"]["details"]["problems"]), (p.stdout, lambda d: d["problems"])):
        try:
            found = pick(json.loads(text))
        except (ValueError, KeyError, TypeError):
            continue
        if found and all(isinstance(x, dict) and "path" in x and "line" in x for x in found):
            return found
    case.skipTest("the installed hal2-cli-roles predates the problems contract (path and line per problem)")


class Files(Farm):
    def test_the_state_is_of_the_kinds_the_manifest_declares(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})  # a conflict no longer unhitches (plan 0522 D18): test_resolve.py's lines
        self.round()
        self.ends({"status": "gate_failed", "run": "https://github.com/x/runs/9"})
        self.round()
        self.call("retry", "--why", "flaky")
        self.round()
        self.ends({"status": "landed", "commit": "c0ffee"}, land=True)
        self.round()
        lines = train_state.lines(str(self.main))
        self.assertEqual([e["kind"] for e in lines], ["formed", "started", "red", "retry", "started", "landed"])
        for e in lines:
            self.assertEqual((e["schema"], bool(e["slot"])), (1, True), e)
            self.assertRegex(e["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        schema = json.loads((SKILL / "schemas/train.schema.json").read_text())
        self.assertEqual(schema["properties"]["kind"]["enum"], list(train_state.KINDS))
        self.assertLessEqual({k for e in lines for k in e}, set(schema["properties"]) | {"at", "slot"})
        manifest = (SKILL / "manifest.toml").read_text()
        for name in (train_state.FILE, train_state.LOG):
            self.assertIn(f'path = "{name}"', manifest)
        checker = next((str(Path(d) / "hal2-cli-roles") for d in os.environ.get("PATH", "").split(os.pathsep)
                        if (Path(d) / "hal2-cli-roles").is_file()), None)  # shutil.which is the fixture's fake
        if not checker:
            self.skipTest("no hal2-cli-roles: the Rust check of the manifest did not run")
        p = subprocess.run([checker, "check", str(self.wm_state), "--manifest", str(SKILL / "manifest.toml"), "--json"],
                           capture_output=True, text=True)
        self.assertEqual((p.returncode, json.loads(p.stdout)["problems"]), (0, []), p.stdout)
        with (self.wm_state / train_state.FILE).open("a") as f:  # and the check does read the role's schema
            f.write(json.dumps({"schema": 1, "at": train_state.utc(), "kind": "derailed", "slot": self.carrier()}) + "\n")
        p = subprocess.run([checker, "check", str(self.wm_state), "--manifest", str(SKILL / "manifest.toml"), "--json"],
                           capture_output=True, text=True)
        # a check with problems exits 1 and carries the report in the error document (plan 0318 step 10)
        found = check_problems(self, p)
        self.assertEqual((p.returncode, [(x["path"].rsplit("/", 1)[-1], x["line"]) for x in found]),
                         (1, [(train_state.FILE, 7)]), p.stderr)
        self.assertRaises(ValueError, train_state.append, str(self.main), "derailed", self.carrier())

    def test_the_landing_is_a_child_of_a_process_that_stays(self):
        with (mock.patch.object(engine, "LAND", [sys.executable, "-c", "import sys; sys.exit(4)"]),
              mock.patch.object(engine.land_name, "refuses", return_value=0)):  # its own test: test_land_name
            self.assertEqual(engine.land(str(self.wm)), 4)
        self.assertEqual(engine.LAND, ["hal2-cli-git", "worktree", "merge-to-main", "--json"])

    def hold_run(self, land_code, pretest_red=False, cloud=False):
        """engine.land with a fake hal2-cli-workqueue: the calls in order, and the hold env each step saw."""
        calls = []
        real = subprocess.run

        def run(argv, **kw):
            if argv[0] == "fake-wq":
                calls.append(" ".join(argv[1:]))
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")
            calls.append("land:" + os.environ.get("HAL2_WORKQUEUE_HOLD", "-"))
            return types.SimpleNamespace(returncode=land_code)

        def pretest(top):
            calls.append("pretest:" + os.environ.get("HAL2_WORKQUEUE_HOLD", "-"))
            return pretest_red

        with (mock.patch.object(workqueue_hold, "WQ", "fake-wq"), mock.patch.object(workqueue_hold.shutil, "which", lambda n: n),
              mock.patch.object(engine.subprocess, "run", run), mock.patch.object(engine, "cli", return_value=(0, "")),
              mock.patch.object(engine.pretest_train, "before_landing", pretest),
              mock.patch.object(engine.next_train, "before_push", lambda top: calls.append("wait")),
              mock.patch.object(engine.hold, "stops", return_value=0),  # no hold (L88's look: its own test)
              mock.patch.object(engine.head_guard, "refuses", return_value=0),  # its own test: UnchangedHead
              mock.patch.object(engine.land_name, "refuses", return_value=0),  # its own test: test_land_name
              mock.patch.object(workqueue_hold, "cloud_train", lambda top: cloud),
              mock.patch("sys.stdout"), mock.patch.dict(os.environ)):
            os.environ.pop("HAL2_WORKQUEUE_HOLD", None)
            os.environ.pop("HAL2_WORKQUEUE_FREEZE", None)
            code = engine.land("/farm/tollman-x")
            after = os.environ.get("HAL2_WORKQUEUE_HOLD")
        return code, calls, after, real

    def test_the_hold_covers_only_the_pretest_never_the_wait_or_the_landing(self):
        """Plan 0467: the train's wait for the run before (up to an hour) and its merge-to-main (whose own hold is
        step-scoped) run without the tollman's hold."""
        code, calls, after, _ = self.hold_run(0)
        hold = calls[0].split("--id ")[1].split()[0]
        self.assertEqual((code, after), (0, None))
        self.assertEqual(calls, [f"hold take --class landing --id {hold} --field tollman-x --owner-pid {os.getpid()}", f"pretest:{hold}",
                                 f"hold release --id {hold}", "wait", "land:-"])

    def test_a_cloud_train_takes_no_hold(self):
        """Plan 0467 D37: a train through merge-to-main-cloud freezes nothing on this Mac, not even its pretest."""
        code, calls, after, _ = self.hold_run(0, cloud=True)
        self.assertEqual((code, after), (0, None))
        self.assertEqual(calls, ["pretest:-", "wait", "land:-"])

    def test_the_hold_is_released_when_the_landing_or_the_pretest_fails(self):
        for land_code, red in ((5, False), (0, True)):
            code, calls, after, _ = self.hold_run(land_code, red)
            self.assertEqual(sum(c.startswith("hold take") for c in calls), 1)
            self.assertTrue(calls[2].startswith("hold release"), calls)
            self.assertEqual(calls[3:], [] if red else ["wait", "land:-"], "a red pretest never waits nor lands")
            self.assertIsNone(after)


class Spawn(unittest.TestCase):
    def test_the_detached_start(self):
        import tempfile
        log = Path(tempfile.mkdtemp()) / "train-landing.log"
        with mock.patch.object(engine.subprocess, "Popen") as popen:
            popen.return_value.pid = 4711
            self.assertEqual(engine.spawn("/farm/tollman-hal2", log, "train-0383-0365"), 4711)
        (argv,), kw = popen.call_args
        self.assertEqual(argv, [sys.executable, str(trains.ENGINE), "land", "--repo", "/farm/tollman-hal2",
                                "--land-ref", "train-0383-0365"])
        self.assertEqual((kw["cwd"], kw["start_new_session"], kw["stdin"], kw["stderr"], kw["stdout"].name),
                         ("/farm/tollman-hal2", True, subprocess.DEVNULL, subprocess.STDOUT, str(log)))


if __name__ == "__main__":
    unittest.main()
