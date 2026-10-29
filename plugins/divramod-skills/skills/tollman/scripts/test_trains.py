"""Hal2 plan 0294 step 6: what the duty `trains` plans. `draft` (steps 1 to 4) runs over one temporary git
repository whose branches are the fields' crops; the state machine (`plan`, `settle`) over data. Nothing is done
here: no queue, no landing, no session (test_engine.py runs whole rounds)."""
# enforces .adr/tollman.md

import functools
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import chain
import gate_car
import proof
import tick
import train_state
import trains
import trial
from gh_fake import FakeGh

import sys
sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import repo_root, sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
AT = "2026-10-13T10:00:00Z"
LANDING = """# the trigger
name: merge-to-main
on:
  push:
    branches: ['land/**']
jobs:
  changes:
    runs-on: a
  lane:
    runs-on: a
    steps: [one, two, three]
  gate:
    runs-on: a
  merge:
    runs-on: a
"""


def ticket(field, pos, head, worktree, **kw):
    return {"slot": field, "position": pos, "state": "waiting", "branch": field, "worktree": str(worktree),
            "seq": pos + 1, "pid": 0, "ready": {"at": AT, "head": head, "by": f"hal2/{field}"}, "train": None,
            "rides_with": None, **kw}


class Crops(unittest.TestCase):
    """One repository: `main` is the barn, every other branch a field's crop (its head is what the field hitched)."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        green = mock.patch.object(trains, "PROVE", lambda *a: {"state": "green", "lines": []})  # Proof: the real one
        green.start()
        self.addCleanup(green.stop)
        self.g("init", "-q", "-b", "main")
        self.write("main", {"a.rs": "a\n", "INTENT.md": "log\n", ".github/workflows/merge-to-main.yml": "on: push\n"}, new=False)

    def g(self, *a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.d, check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, name, files, new=True):
        if new:
            self.g("checkout", "-q", "-b", name, "main")
        for f, text in files.items():
            (Path(self.d) / f).parent.mkdir(parents=True, exist_ok=True)
            (Path(self.d) / f).write_text(text)
        self.g("add", "-A")
        self.g("commit", "-q", "-m", name)
        return self.g("rev-parse", "HEAD")

    def queue(self, **crops):
        """field={file: text} in queue order -> the ready tickets."""
        return [ticket(f, n, self.write(f, files), self.d) for n, (f, files) in enumerate(crops.items())]

    def draft(self, tickets, own="tollman-hal2"):
        return trains.draft(self.d, tickets, own, "main", "main")

    def cars(self, d):
        return [c["field"] for c in d["cars"]]

    def servant_field(self):
        """A worktree folder holding `plans/LEAD`, a foreman's marker (<foreman field> <plan> <step>)."""
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / "plans").mkdir()
        (folder / "plans/LEAD").write_text("07 0383-train-rules 16\n")
        return str(folder)


class Trial(Crops):
    def test_a_real_trial_merge_moves_no_ref_and_names_the_files_that_conflict(self):
        q = self.queue(**{"05": {"a.rs": "five\n", "INTENT.md": "log\n05\n"}, "07": {"b.rs": "b\n"},
                          "09": {"a.rs": "other\n"}, "11": {"INTENT.md": "log\n11\n"}})
        five, b, a, intent = (t["ready"]["head"] for t in q)
        before = self.g("for-each-ref")
        commit, files = trial.merge(self.d, five, b)
        self.assertEqual((self.g("rev-list", "--parents", "-n", "1", commit).split()[1:], files), ([five, b], []))
        self.assertEqual(trial.merge(self.d, commit, a)[1], ["a.rs"])
        self.assertEqual(trial.merge(self.d, commit, intent)[1], ["INTENT.md"],
                         "an append-only file conflicts too: nothing resolves it for a foreman")
        self.assertEqual(trial.merge(self.d, "main", "0" * 40), (None, []), "git cannot say")
        self.assertEqual(self.g("for-each-ref"), before, "no ref moves")
        self.assertEqual(self.g("status", "--porcelain"), "")
        d = self.draft(q)
        self.assertEqual((self.cars(d), [u["field"] for u in d["unhitched"]]), (["05", "07"], ["09", "11"]))


class Draft(Crops):
    def test_two_ready_wagons_are_one_train_in_queue_order(self):
        q = self.queue(**{"07": {"seven.rs": "7\n"}, "09": {"nine.rs": "9\n"}})
        (Path(self.d) / "plans").mkdir()
        (Path(self.d) / "plans/CURRENT_PLAN").write_text("0294-tollman-role\n")
        d = self.draft(list(reversed(q)))
        self.assertEqual(d["cars"], [
            {"field": f, "branch": f, "head": t["ready"]["head"], "plan": "0294-tollman-role"}
            for f, t in zip(("07", "09"), q)])
        self.assertEqual((d["unhitched"], d["waiting"], d["alone"], d["base"]), ([], [], False, "main"))

    def test_no_ready_ticket_is_no_train_and_every_clean_car_rides(self):
        # Hal2 plan 0463 D1 (the user, 2026-10-29): no car limit; every clean ready car rides.
        waiter = dict(ticket("03", 0, "x", self.d), ready=None)
        self.assertEqual(self.draft([waiter])["cars"], [])
        q = self.queue(**{f"0{n}": {f"f{n}.rs": "x\n"} for n in range(1, 9)})
        d = self.draft(q)
        self.assertEqual((self.cars(d), d["alone"], d["waiting"]), ([f"0{n}" for n in range(1, 9)], False, []))
        self.assertEqual(self.cars(self.draft(q[6:])), ["07", "08"], "fewer when fewer are ready")

    def test_fourteen_clean_ready_cars_are_one_train(self):
        # Hal2 plan 0463 D1: the old cap of 6 is gone; 14 clean cars ride as one train, nothing waits.
        q = self.queue(**{f"{n:02d}": {f"f{n}.rs": "x\n"} for n in range(1, 15)})
        d = self.draft(q)
        self.assertEqual((self.cars(d), d["alone"], d["waiting"], d["unhitched"]),
                         ([f"{n:02d}" for n in range(1, 15)], False, [], []))

    def test_what_cannot_ride_is_unhitched_at_once(self):
        q = self.queue(**{"31": {"servant.rs": "s\n"}, "07": {"seven.rs": "7\n"}, "05": {"gone.rs": "g\n"}})
        q[2]["worktree"] = str(Path(self.d) / "no-such-field")
        q[0]["worktree"] = self.servant_field()  # D16: a servant's field is the one holding plans/LEAD, not field 31
        landed = ticket("04", 3, self.g("rev-parse", "main"), self.d)
        own = ticket("tollman-hal2", 4, q[1]["ready"]["head"], self.d)
        other = ticket("06", 5, q[1]["ready"]["head"], self.d, rides_with="08")
        d = self.draft([*q, landed, own, other])
        self.assertEqual(self.cars(d), ["07"], "the own field and a car of another carrier are not ours")
        self.assertEqual([(u["field"], u["tell"], u["why"]) for u in d["unhitched"]],
                         [("31", "servant", "a servant's field (plans/LEAD) never rides"),
                          ("05", None, "its worktree is gone"), ("04", None, "its head is in the barn already")])

    def test_a_wagon_that_conflicts_is_unhitched_with_its_files_and_the_rest_rides(self):
        q = self.queue(**{"07": {"a.rs": "seven\n"}, "09": {"a.rs": "nine\n"}, "11": {"c.rs": "c\n"}})
        d = self.draft(q)
        self.assertEqual(self.cars(d), ["07", "11"])
        (u,) = d["unhitched"]
        self.assertEqual((u["field"], u["files"], u["ahead"], u["tell"]), ("09", ["a.rs"], ["07"], "conflict"))
        self.assertEqual(u["why"], "conflicts with the cars ahead in a.rs")

    def test_a_conflict_with_the_barn_is_named_so(self):
        q = self.queue(**{"07": {"seven.rs": "7\n"}, "09": {"a.rs": "nine\n"}})
        self.g("checkout", "-q", "main")
        self.write("main", {"a.rs": "the barn moved\n"}, new=False)
        (u,) = self.draft(q)["unhitched"]
        self.assertEqual((u["field"], u["ahead"], u["why"]), ("09", [], "conflicts with the barn in a.rs"))

    def test_the_alone_rule(self):
        # D12: only a car changing what starts the landing's run rides alone, the only car of its train.
        why = "rides alone in the next train: it changes what starts the landing's run (.github/workflows/merge-to-main.yml: " \
              "on, name or run-name)"
        q = self.queue(**{"07": {".github/workflows/merge-to-main.yml": "on: pull_request\n"}, "09": {"nine.rs": "9\n"},
                          "11": {"eleven.rs": "11\n"}})
        first = self.draft(q)
        self.assertEqual((self.cars(first), first["alone"]), (["07"], True))
        self.assertEqual(first["waiting"], [{"field": f, "why": "rides in the next train, after 07, which rides alone"}
                                            for f in ("09", "11")])
        self.assertEqual(trains.train_actions("/f", first, {})[-1]["text"], "wagon train: 07 (alone)")
        later = self.draft([dict(q[1], position=0), dict(q[0], position=1), q[2]])
        self.assertEqual((self.cars(later), later["alone"], later["unhitched"]), (["09", "11"], False, []))
        self.assertEqual(later["waiting"], [{"field": "07", "why": why}])

    def test_what_starts_the_landing_s_run(self):
        self.g("checkout", "-q", "main")
        self.write("main", {".github/workflows/merge-to-main.yml": LANDING}, new=False)
        crops = {"05": {".github/workflows/merge-to-main.yml": LANDING.replace("  merge:", "  # the merge\n  merge:")},
                 "06": {".github/workflows/merge-to-main.yml": LANDING.replace("# the trigger", "# when")},
                 "07": {".github/workflows/merge-to-main.yml": LANDING.replace("land/**", "landing/**")},
                 "08": {".github/workflows/merge-to-main.yml": LANDING.replace("name: merge", "name: land")},
                 "09": {".github/workflows/merge-to-main.yml": LANDING.replace("on:", "run-name: x\non:")}}
        heads = {f: t["ready"]["head"] for f, t in zip(crops, self.queue(**crops))}
        self.g("checkout", "-q", "-b", "10", "main")
        self.g("mv", ".github/workflows/merge-to-main.yml", ".github/workflows/dev-merge-to-main.yml")
        self.g("commit", "-q", "-m", "10")
        heads["10"] = self.g("rev-parse", "HEAD")
        self.g("checkout", "-q", "-b", "11", "main")
        self.g("rm", "-q", ".github/workflows/merge-to-main.yml")
        self.g("commit", "-q", "-m", "11")
        heads["11"] = self.g("rev-parse", "HEAD")
        run = "it changes what starts the landing's run (.github/workflows/merge-to-main.yml: on, name or run-name)"
        self.assertEqual({f: gate_car.alone_why(self.d, "main", h) for f, h in heads.items()},
                         {"05": None, "06": None, "07": run, "08": run, "09": run,
                          "10": "it renames the landing workflow .github/workflows/merge-to-main.yml",
                          "11": "it removes the landing workflow .github/workflows/merge-to-main.yml"})

    def test_gate_cars_ride_with_the_others_as_one_train(self):
        # Hal2 plan 0333 step 3 (D3), 2026-10-14: the gate cars 09, 05, 08, 14 and 21 rode as five trains of one;
        # step 10 (D12): they ride with 17 and 22 as one train (plan 0463: no car limit).
        gate = {"09": ".github/workflows/nine.yml", "05": "code/bash/scripts/gate/five.sh",
                "08": ".github/hal2-caches.toml", "14": ".github/workflows/fourteen.yml",
                "21": "code/bash/scripts/gate/twentyone.sh", "22": "code/bash/scripts/gate/main.sh"}
        crops = {f: {path: f + "\n"} for f, path in gate.items()}
        q = self.queue(**{"09": crops["09"], "05": crops["05"], "17": {"seventeen.rs": "17\n"}, "08": crops["08"],
                          "14": crops["14"], "21": crops["21"], "22": crops["22"]})
        d = self.draft(q)
        self.assertEqual((self.cars(d), d["alone"], d["unhitched"]),
                         (["09", "05", "17", "08", "14", "21", "22"], False, []))
        self.assertEqual(d["waiting"], [])
        self.assertEqual(trains.train_actions("/f", d, {})[-1]["text"], "wagon train: 09, 05, 17, 08, 14, 21, 22")

    def test_the_replay_of_09_08_21_22_is_one_train(self):
        # D12's why: on 2026-10-14 the alone rule kept 09, 08, 21 and 22 out of a train although their trial merges
        # were clean; each with the gate files it changed then (board.jsonl's ready heads), behind a normal car.
        self.g("checkout", "-q", "main")
        self.write("main", {".github/workflows/merge-to-main.yml": LANDING, ".github/hal2-runners.toml": "[a]\n",
                            ".github/hal2-changes.toml": "[jobs]\n",
                            "code/bash/scripts/gate/plan.sh": "plan\n", "code/bash/scripts/gate/main.sh": "main\n"},
                   new=False)
        q = self.queue(**{
            "17": {"engine.py": "17\n"},
            "09": {"code/bash/scripts/gate/plan.sh": "plan\nselect\n", "code/bash/scripts/gate/test.bats": "09\n"},
            "08": {".github/hal2-runners.toml": "[a]\n[b]\n", ".github/workflows/t460p-host.yml": "on: push\n",
                   ".github/workflows/merge-to-main.yml": LANDING.replace("lane:\n    runs-on: a",
                                                                          "lane:\n    runs-on: b")},
            "21": {".github/hal2-changes.toml": "[jobs]\nx = 1\n", "code/bash/scripts/gate/jobs/x.sh": "21\n"},
            "22": {".github/workflows/merge-to-main.yml": LANDING + "  fail-fast-a:\n    runs-on: a\n",
                   "code/bash/scripts/gate/main.sh": "main\nstop-run\n"}})
        d = self.draft(q)
        self.assertEqual((self.cars(d), d["alone"], d["unhitched"], d["waiting"]),
                         (["17", "09", "08", "21", "22"], False, [], []))

    def test_what_the_field_holds_beyond_the_barn_is_under_the_cars(self):
        role = self.write("wm", {"roles/tollman/ROLE.md": "mine\n"})
        self.assertEqual(trains.base_of(self.d, "main", self.g("rev-parse", "main")), "main")
        self.assertEqual(trains.base_of(self.d, "main", None), "main")
        base = trains.base_of(self.d, "main", role)
        self.assertEqual(self.g("rev-list", "--parents", "-n", "1", base).split()[1:],
                         [self.g("rev-parse", "main"), role])


class Proof(Crops):
    """Hal2 plan 0333 step 4 (cause A): no car rides without its light gate checks green on its hitched head."""

    PLAN = "0255-plugin-tmux-2-move-tmux-plugin-here"

    def setUp(self):
        super().setUp()
        cache = Path(tempfile.mkdtemp()) / "cache" / "proof"
        self.addCleanup(shutil.rmtree, cache.parents[1], True)
        real = mock.patch.object(trains, "PROVE", functools.partial(proof.verdict, cache=cache))
        real.start()
        self.addCleanup(real.stop)
        names = repo_root(__file__) / "code/python/scripts/names-inventory"
        files = {f"{proof.NAMES.rsplit('/', 1)[0]}/{p.name}": p.read_text() for p in names.glob("*.py")
                 if not p.name.startswith("test_")}
        files[f"plans/{self.PLAN}/plan.md"] = "---\nstatus: open\n---\n# Plan 0255\n"  # an open plan is no history
        self.g("checkout", "-q", "main")
        self.write("main", files, new=False)  # the barn's names check, as the field has it

    def test_06s_car_with_an_old_word_in_a_prose_line_is_unhitched_with_the_finding(self):
        # 2026-10-14 08:17: 06's car at d192125ca rode with "the slot's pane" in plan 0255's uat.md, and train
        # 38534070998 was red in python-lint's names check; one car's line cost the whole train's run.
        uat = f"plans/{self.PLAN}/uat.md"
        (q,) = self.queue(**{"06": {uat: "# UATs\n\nExpected: 1 shows the slot's pane (or a window in session "
                                         "`hosts`), no popup.\n"}})
        d = self.draft([q])
        self.assertEqual(self.cars(d), [], "the car does not ride")
        (u,) = d["unhitched"]
        self.assertEqual((u["field"], u["tell"]), ("06", "proof"))
        self.assertEqual(u["lines"], [f"names: {uat}:3: slot — use worktree"])
        (unhitch, told) = trains.train_actions("/f", d, {"06": "%6"})
        self.assertEqual((unhitch["kind"], told["kind"], told["pane"]), ("unhitch", "unhitched", "%6"))
        self.assertIn(f"{uat}:3: slot — use worktree", told["text"])
        self.assertTrue(told["text"].endswith("Fix it, push and report it ready again (`hal2-cli-git worktree "
                                              "queue ready`)."), told["text"])

    def test_a_clean_car_rides_and_one_not_at_its_hitched_head_waits(self):
        q = self.queue(**{"07": {"plans/0301-x/notes.md": "the worktree's pane\n"}, "09": {"nine.rs": "9\n"}})
        d = self.draft(q)  # the checkout is at 09's head: 07's field moved on
        self.assertEqual((self.cars(d), d["unhitched"]), (["09"], []))
        self.assertEqual(d["waiting"][0]["field"], "07")
        self.assertTrue(d["waiting"][0]["why"].startswith("no proof yet: the field is at "), d["waiting"])


TRAIN = {"train": "07+09@" + AT, "carrier": "tollman-hal2", "base": "b" * 40, "state": "landing", "starts": 1,
         "pid": 4711, "unhitched": [],
         "cars": [{"field": "07", "branch": "07", "head": "7" * 40, "plan": "0294-tollman-role"},
                  {"field": "09", "branch": "09", "head": "9" * 40, "plan": ""}]}


def shape(actions):
    return [(a["kind"], a["do"], a["slot"]) for a in actions]


class Settle(unittest.TestCase):
    def setUp(self):
        FakeGh().start(self)  # triage reads gh (plan 0360 step 5): never a real call

    def test_landed_tells_every_car_s_foreman_in_the_barn(self):
        out = trains.settle("/f", TRAIN, {"status": "landed", "commit": "c1", "run": "https://x/runs/9"}, {"07": "%7"})
        self.assertEqual(shape(out), [("landed", "run", "-"), ("in-the-barn", "send", "07"), ("in-the-barn", "send", "09"),
                                      ("chain", "run", "-")])
        go = out[-1]  # plan 0333 step 6: the same round goes on to the next train
        self.assertEqual((go["argv"][1:], go["after"], go["key"], go["on_fail"][0]["kind"]),
                         ([str(chain.CLI), "chain", "--in-tick", "--repo", "/f"], out[0]["key"],
                          "chain:" + out[0]["key"], "train-stuck"))
        self.assertEqual(out[0]["argv"][1:], [str(trains.ENGINE), "landed", "--run", "https://x/runs/9", "--commit",
                                              "c1", "--repo", "/f"])
        self.assertEqual((out[1]["pane"], out[2]["pane"]), ("%7", None))
        self.assertTrue(out[1]["text"].startswith("tollman (wagon train): your crop is in the barn (the train of "
                                                  "07, 09, https://x/runs/9): /merge-from-main, finish the plan"), out[1]["text"])
        self.assertEqual({a["after"] for a in out[1:]}, {out[0]["key"]})
        for result in ({"status": "nothing"}, {"status": "shipping", "commit": "c1"}):
            self.assertEqual(shape(trains.settle("/f", TRAIN, result, {}))[0], ("landed", "run", "-"), result)

    def test_red_is_one_wake_with_the_run_s_address_and_the_cars(self):
        result = {"status": "gate_failed", "run": "https://x/runs/9", "message": "the gate is red",
                  "red": [{"name": "linux / rust-test"}, {"name": "mac / swift"}]}
        out = trains.settle("/f", TRAIN, result, {})
        self.assertEqual(shape(out), [("red", "run", "-"), ("train-failed", "wake", "-")])
        self.assertEqual(out[0]["argv"][2:], ["red", "--status", "gate_failed", "--run", "https://x/runs/9", "--why",
                                              "linux / rust-test, mac / swift", "--repo", "/f"])
        for part in ("did not land (gate_failed): linux / rust-test, mac / swift", "Run: https://x/runs/9.",
                     "Cars: 07 (0294-tollman-role), 09 (09).", "frozen (plan 0360 D3)",
                     "Triage: a car's red", "tollman.py triage 9", "waits for its fix"):
            self.assertIn(part, out[1]["text"])
        self.assertEqual((out[1]["after"], out[1]["key"]), (out[0]["key"], "train-red:9"))
        other = trains.settle("/f", TRAIN, {"status": "conflict", "message": "a.rs conflicts"}, {})
        self.assertEqual((shape(other), other[0]["argv"][2:6]),
                         ([("red", "run", "-"), ("train-failed", "wake", "-")], ["red", "--status", "conflict", "--why"]))
        self.assertIn("tollman.py retry --why", other[1]["text"], "no run to triage: the old wake")
        self.assertEqual(other[1]["key"], f"train-red:{TRAIN['train']}:1")

    def test_interrupted_starts_the_same_landing_again_a_few_times(self):
        for result in (None, {"status": "interrupted", "message": "its parent is gone"}, {"status": "testing"}):
            out = trains.settle("/f", TRAIN, result, {})
            self.assertEqual((shape(out), out[0]["argv"][2:]), ([("restart", "run", "-")], ["restart", "--repo", "/f"]))
        stuck = trains.settle("/f", dict(TRAIN, starts=trains.MAX_STARTS), None, {})
        self.assertEqual(shape(stuck), [("red", "run", "-"), ("train-failed", "wake", "-")])
        self.assertIn(f"its landing ended without a result {trains.MAX_STARTS} times", stuck[1]["text"])


class Plan(unittest.TestCase):
    """The state machine over data: the field `/f/tollman-hal2` does not exist, so nothing is drafted."""

    TOP = "/no/such/farm/tollman-hal2"
    FORMED = {"schema": 1, "at": AT, "kind": "formed", "slot": "tollman-hal2", "train": TRAIN["train"],
              "cars": TRAIN["cars"], "base": TRAIN["base"]}
    STARTED = {"schema": 1, "at": AT, "kind": "started", "slot": "tollman-hal2", "train": TRAIN["train"],
               "pid": 4711}

    def setUp(self):
        FakeGh().start(self)  # a live landing's watch reads gh (plan 0360 step 5): never a real call

    def plan(self, rows, tickets=(), alive=(), result=None):
        return trains.plan(self.TOP, "/no/such/farm", list(tickets), rows, {}, alive=lambda pid: pid in alive,
                           result=lambda main: result)

    def line(self, kind, **kw):
        return {"schema": 1, "at": AT, "kind": kind, "slot": "tollman-hal2", "train": TRAIN["train"], **kw}

    def test_a_running_landing_is_never_touched(self):
        self.assertEqual(self.plan([self.FORMED, self.STARTED], alive={4711}), [], "its run not found yet: only watched")
        mine = {"slot": "tollman-hal2", "position": 0, "pid": 99, "state": "active"}
        self.assertEqual(self.plan([], [mine], alive={99}), [], "a landing of the field that is no train of ours")

    def test_a_red_train_waits_for_the_session_s_word(self):
        red = self.line("red", status="gate_failed")
        self.assertEqual(self.plan([self.FORMED, self.STARTED, red]), [])
        again = self.plan([self.FORMED, self.STARTED, red, self.line("retry", why="flaky")])
        self.assertEqual((shape(again), again[0]["argv"][2]), ([("restart", "run", "-")], "restart"))
        split = self.plan([self.FORMED, self.STARTED, red,
                           dict(self.line("unhitched", why="its test fails", by="user"), slot="09")])
        self.assertEqual(shape(split), [("breakup", "run", "-"), ("unhitched", "send", "09")])
        self.assertEqual(split[0]["argv"][2:5], ["breakup", "--why", "split after red by the user"])
        self.assertIn("field 09 is unhitched from the red train by the user: its test fails.", split[1]["text"])

    def test_a_leftover_mark_is_broken_up(self):
        mark = {"carrier": "tollman-hal2", "cars": [{"field": "05"}], "at": AT}
        mine = {"slot": "tollman-hal2", "position": 0, "pid": 0, "state": "waiting", "train": mark}
        left = self.plan([], [mine])
        self.assertEqual((shape(left), left[0]["argv"][4], left[0]["key"]),
                         ([("breakup", "run", "-")], "a mark without a train of ours", f"leftover:{AT}"))
        ours = dict(mine, train=dict(mark, cars=[{"field": "07"}, {"field": "09"}]))
        self.assertEqual(shape(self.plan([self.FORMED, self.STARTED], [ours], result={"status": "landed"}))[0],
                         ("landed", "run", "-"))

    def test_every_action_carries_a_key_and_a_failed_change_wakes_the_session(self):
        rows = [self.FORMED, self.STARTED]
        planned = (self.plan(rows, result={"status": "landed"}) + self.plan(rows, result={"status": "gate_failed"})
                   + self.plan(rows) + self.plan([self.FORMED]))
        self.assertEqual([a for a in planned if not a.get("key")], [], "D22: tick.fresh drops keyless actions")
        for a in (a for a in planned if a["do"] == "run"):
            (stuck,) = a["on_fail"]
            self.assertEqual((stuck["kind"], stuck["do"], stuck["slot"], stuck["key"]),
                             ("train-stuck", "wake", "-", "stuck:" + a["key"]))
            self.assertIn(a["argv"][:2], ([trains.sys.executable, str(trains.ENGINE)],
                                          [trains.sys.executable, str(chain.CLI)]), "an engine verb, or the chain")
        log = [{"at": "2026-10-13T12:00:00", "key": a["key"]} for a in planned]
        now = tick.dt.datetime(2026, 10, 13, 12, 5)
        self.assertEqual(tick.fresh(planned, log, now, "tollman"), [], "a second round does nothing again")
        self.assertEqual(len(tick.fresh(planned, [], now, "tollman")), len(planned),
                         "and no action names the tollman's own field: none is held back")


class Frozen(unittest.TestCase):
    """Hal2 plan 0360 D3, D7: a train is frozen at forming; nothing leaves it, no wait limit ends it. Each case was a
    breakup and a re-form of whatever the queue held then (plan 0360 survey part 2: "Not frozen today")."""

    TOP, FORMED, STARTED, plan, line = Plan.TOP, Plan.FORMED, Plan.STARTED, Plan.plan, Plan.line
    MARK = {"carrier": "tollman-hal2", "cars": [{"field": "05"}], "at": AT}

    def mine(self, **kw):
        return {"slot": "tollman-hal2", "position": 0, "pid": 0, "state": "waiting", "train": self.MARK, **kw}

    def test_a_train_whose_landing_never_started_lands_as_it_is(self):
        later = ticket("11", 1, "1" * 40, "/no/such/farm/11")  # hitched after the train formed
        out = self.plan([self.FORMED], [later])
        self.assertEqual((shape(out), out[0]["argv"][2], out[0]["key"]),
                         ([("restart", "run", "-")], "restart", f"resume:{TRAIN['train']}"), "the same cars")

    def test_a_mark_naming_other_cars_breaks_no_train_up(self):
        rows = [self.FORMED, self.STARTED]
        self.assertEqual(shape(self.plan(rows, [self.mine()])), [("restart", "run", "-")],
                         "its landing ended without a word: the same train again, the restart marks its own cars")
        self.assertEqual(shape(self.plan(rows, [self.mine()], result={"status": "landed"}))[0], ("landed", "run", "-"))
        red = self.line("red", status="gate_failed")
        self.assertEqual(self.plan(rows + [red], [self.mine()]), [], "a red train waits")

    def test_a_split_breaks_up_only_on_the_user_s_word(self):
        rows = [self.FORMED, self.STARTED, self.line("red", status="gate_failed")]
        session = dict(self.line("unhitched", why="its test fails"), slot="09")
        self.assertEqual(self.plan(rows + [session]), [], "an unhitch without the user's word leaves the train red")
        user = dict(session, by="user")
        split = self.plan(rows + [user])
        self.assertEqual(shape(split), [("breakup", "run", "-"), ("unhitched", "send", "09")])
        self.assertEqual(split[0]["argv"][2:6], ["breakup", "--why", "split after red by the user", "--by-user"])

    def test_a_fixing_train_is_frozen_as_a_red_one(self):
        """Plan 0360 step 6: a red train with a fix order open waits for the fix; nothing is drafted or broken up."""
        rows = [self.FORMED, self.STARTED, self.line("red", status="gate_failed"),
                self.line("order", field="07", branch="07-train-fix", base="b" * 40, why="x", id="07-fix-1")]
        self.assertEqual(train_state.standing(rows)["state"], "fixing")
        self.assertEqual(self.plan(rows, [self.mine(), ticket("11", 1, "1" * 40, "/no/such/farm/11")]), [])
        session = dict(self.line("unhitched", why="its test fails"), slot="09")
        self.assertEqual(self.plan(rows + [session]), [], "an unhitch without the user's word leaves it standing")
        fixed = self.line("fixed", field="07", id="07-fix-1", sha="c" * 40, commit="d" * 40)
        again = self.plan(rows + [fixed])
        self.assertEqual((shape(again), again[0]["key"]), ([("restart", "run", "-")], f"retry:{TRAIN['train']}:1"))

    def test_no_wait_limit_ends_a_red_train(self):
        """D7: a red train a week old still stands, and its round neither re-runs nor wakes anything."""
        red = self.line("red", status="gate_failed")
        rows = [self.FORMED, self.STARTED, red]
        self.assertEqual(train_state.standing(rows)["state"], "red")
        self.assertEqual(self.plan(rows, [ticket("11", 1, "1" * 40, "/no/such/farm/11")]), [])
        interrupted = [self.FORMED] + [self.STARTED] * trains.MAX_STARTS + [self.line("red", status="interrupted")]
        self.assertEqual(train_state.standing(interrupted)["state"], "red", "MAX_STARTS only wakes; the train stands")
        self.assertEqual(self.plan(interrupted), [])


class Chain(unittest.TestCase):
    """Hal2 plan 0333 step 6 (cause C): one call goes on link after link until a wait, at most MAX_LINKS."""

    @staticmethod
    def ran(kind, code=0, do="run", slot="-"):
        return {"kind": kind, "do": do, "slot": slot, "exit": code}

    def test_a_link_goes_on_only_after_landed_or_breakup_that_started_no_landing(self):
        ran = self.ran
        self.assertIsNone(chain.stop([ran("landed"), ran("in-the-barn", None, "send", "07")]))
        self.assertIsNone(chain.stop([ran("breakup", tick.OFFLINE)]), "offline is no failure")
        self.assertEqual(chain.stop([]), "nothing to do")
        self.assertEqual(chain.stop([ran("breakup"), ran("unhitched", None, "send", "09"), ran("form")]),
                         "a landing started")
        self.assertEqual(chain.stop([ran("restart")]), "a landing started")
        self.assertEqual(chain.stop([ran("breakup", 1), ran("form")]), "failed: breakup")
        self.assertEqual(chain.stop([ran("unhitch"), ran("unhitched", None, "send", "31")]), "a wait")
        self.assertEqual(chain.stop([ran("red"), ran("train-failed", None, "wake")]), "a wait")

    def test_the_chain_is_bounded_and_every_link_is_logged(self):
        logged, links = [], iter([[self.ran("landed")], [self.ran("breakup")], [self.ran("landed")]])
        with mock.patch.object(chain, "link", lambda *a: next(links)), \
                mock.patch.object(chain.tick, "execute", lambda a, *rest: logged.append((a["kind"], a["do"], a["text"]))), \
                mock.patch.object(chain.mtm_scan, "main_checkout", return_value="/m"):
            r = chain.go("/f", None, None)
        self.assertEqual((len(r["links"]), r["why"], r["items"]), (3, "3 links: the next round goes on", 0))
        self.assertEqual(logged, [("chain", "record", "chain link 1: landed -"), ("chain", "record", "chain link 2: breakup -"),
                                  ("chain", "record", "chain link 3: landed -")])
        self.assertEqual(chain.report(r)[1].splitlines()[-1], "chain stops: 3 links: the next round goes on")


class State(unittest.TestCase):
    def test_the_fold(self):
        formed, started = Plan.FORMED, Plan.STARTED
        self.assertIsNone(train_state.standing([]))
        self.assertEqual(train_state.standing([formed])["state"], "formed")
        t = train_state.standing([formed, started, started])
        self.assertEqual((t["state"], t["starts"], t["pid"], t["base"]), ("landing", 2, 4711, "b" * 40))
        red = dict(started, kind="red", status="gate_failed", run="u")
        self.assertEqual(train_state.standing([formed, started, red])["state"], "red")
        other = dict(started, kind="landed", train="another@x")
        self.assertEqual(train_state.standing([formed, started, red, other])["state"], "red", "another train's line")
        plain = {"kind": "unhitched", "slot": "09", "why": "conflict"}  # no car of the train: a ready ticket's
        self.assertEqual(train_state.standing([formed, started, red, plain])["unhitched"], [])
        order = dict(started, kind="order", field="07", id="07-fix-1")
        t = train_state.standing([formed, started, red, order, dict(order, field="09", id="09-fix-1")])
        self.assertEqual((t["state"], [o["id"] for o in t["orders"]]), ("fixing", ["07-fix-1", "09-fix-1"]))
        t = train_state.standing([formed, started, red, order, dict(order, kind="fixed")])
        self.assertEqual((t["state"], t["fixed"], t["orders"]), ("retry", True, []))
        self.assertFalse(train_state.standing([formed, started, red, order, dict(order, kind="fixed"), started])["fixed"])
        for end in ("landed", "cleared"):
            self.assertIsNone(train_state.standing([formed, started, dict(started, kind=end)]))

    def test_a_pid_another_process_got_is_not_the_landing(self):
        sleeper = [trains.sys.executable, "-c", "import time; time.sleep(60)"]
        ours = subprocess.Popen([*sleeper, "engine.py land"])  # as `ps` shows the train's detached process
        other = subprocess.Popen(sleeper)
        try:
            self.assertTrue(train_state.alive(ours.pid))
            self.assertFalse(train_state.alive(other.pid), "alive, but not a landing: a reused pid")
        finally:
            for p in (ours, other):
                p.kill()
                p.wait()
        self.assertFalse(train_state.alive(ours.pid) or train_state.alive(None))

    def test_utc_with_z_and_whole_seconds(self):
        naive = tick.dt.datetime(2026, 10, 13, 12, 0, 5, 999)
        self.assertRegex(train_state.utc(naive), r"^2026-10-1[234]T\d\d:\d\d:05Z$")
        aware = tick.dt.datetime(2026, 10, 13, 12, 0, 5, tzinfo=tick.dt.timezone(tick.dt.timedelta(hours=2)))
        self.assertEqual(train_state.utc(aware), "2026-10-13T10:00:05Z")
        self.assertEqual(json.loads(json.dumps(train_state.KINDS)),
                         ["formed", "yard", "regenerated", "pretest", "started", "run", "red", "order", "fixed", "pause",
                          "resumed", "retry", "unhitched", "barn", "landed", "cleared"])


if __name__ == "__main__":
    unittest.main()
