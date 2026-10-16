"""Hal2 plan 0294 step 6: the train engine in whole rounds, on engine_farm.py's farm: the foremen's fields 07, 09
and 11 hitch, the wagon master's tick forms, lands and settles their trains. `hal2-cli-git` is the farm's `Gate`
(the merge queue as data) and no landing is ever started. No timer, no session, no real queue."""

import dataclasses
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import tick
import train_state
import trains
import wagon_master
from engine_farm import OWN, Farm, out
from test_farmer import git

SKILL = Path(__file__).resolve().parents[1]


class Forming(Farm):
    def test_a_dry_run_forms_one_train_from_two_ready_wagons_and_writes_nothing(self):
        self.crop("07", {"seven.txt": "7"}, plan="0294-wagon-master-role")
        self.crop("09", {"nine.txt": "9"})
        code, text = self.call("train", "--dry-run", "--json", repo=self.main)
        d = json.loads(text)
        self.assertEqual((code, d["field"], d["standing"], d["alone"], d["unhitched"], d["waiting"]),
                         (0, OWN, None, False, [], []))
        self.assertEqual([(c["field"], c["plan"], c["head"]) for c in d["cars"]],
                         [("07", "0294-wagon-master-role", self.gate.of("07")["ready"]["head"]),
                          ("09", "", self.gate.of("09")["ready"]["head"])])
        code, text = self.call("train", "--dry-run")
        self.assertIn("standing: no train\nnext train: 07 (0294-wagon-master-role, ", text)
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
        self.assertEqual((self.last, self.spawned), ([("form", "run", "-")], [OWN]))

    def test_a_round_merges_the_cars_marks_the_train_and_starts_its_landing(self):
        self.crop("07", {"seven.txt": "7"}, plan="0294-wagon-master-role")
        self.crop("09", {"nine.txt": "9"})
        base = out(self.wm, "rev-parse", "HEAD")
        self.round()
        self.assertEqual(self.last, [("form", "run", "-")])
        self.assertEqual(self.subjects(), ["Merge branch '09' into wagon-master-hal2",
                                           "Merge branch '07' into wagon-master-hal2", "nine.txt", "seven.txt"])
        self.assertEqual((self.wm / "plans/CURRENT_PLAN").read_text(), "0294-wagon-master-role + 09\n")
        self.assertEqual(self.gate.calls, [["worktree", "queue", "train", OWN, "07", "09"]], "marked, then started")
        self.assertEqual(self.spawned, [OWN])
        self.assertEqual(self.state(), [("formed", OWN), ("started", OWN)])
        t = self.train()
        self.assertEqual((t["state"], t["starts"], t["pid"], t["base"], [c["field"] for c in t["cars"]]),
                         ("landing", 1, 40001, base, ["07", "09"]))
        self.assertEqual(self.gate.of("07")["ready"]["head"], t["cars"][0]["head"], "a car keeps its ready ticket")

        self.alive.add(40001)  # the landing runs: the tick never waits for it, and the field stays as it is (D22)
        self.assertIsNone(tick.slot_problem(str(self.wm), wagon_master.WIRING))
        plain = dataclasses.replace(wagon_master.WIRING, carries=None)
        self.assertIn("holds more than roles/wagon-master/ROLE.md: nine.txt", tick.slot_problem(str(self.wm), plain))
        r = self.round()
        self.assertEqual((self.last, [a["kind"] for a in r["planned"] if a["duty"] == "frame"]), ([], []),
                         "no merge-from-main while the train stands")
        d = json.loads(self.call("train", "--dry-run", "--json", repo=self.main)[1])
        self.assertEqual((d["standing"]["state"], d["cars"]), ("landing", []), "its cars are not the next train's")
        self.assertEqual((self.spawned, len(self.gate.calls)), ([OWN], 1))

    def test_a_conflicting_wagon_is_unhitched_and_told_and_the_other_rides(self):
        self.commit(self.main, "shared.txt", "base\n", push=True)
        git(self.wm, "merge", "-q", "--ff-only", "main")
        self.crop("07", {"shared.txt": "seven\n"})
        self.crop("09", {"shared.txt": "nine\n"})
        self.crop("11", {"eleven.txt": "11"})
        self.panes = {"09": "%9"}
        self.round()
        self.assertEqual(self.last, [("unhitch", "run", "09"), ("unhitched", "send", "09"), ("form", "run", "-")])
        self.assertEqual(self.gate.calls, [["worktree", "queue", "ready", "09", "--clear"],
                                           ["worktree", "queue", "train", OWN, "07", "11"]])
        self.assertIsNone(self.gate.of("09"))
        ((pane, text),) = self.typed
        self.assertEqual(pane, "%9")
        self.assertRegex(text, r"^wagon-master \[09-1\] \(wagon train\): field 09 is unhitched: its crop conflicts "
                               r"with the cars ahead \(07\) in shared.txt. Restock \(/mfm\) once the train of 07 is in "
                               r"the barn, resolve it, push and report it ready again")
        self.assertEqual(self.state(), [("unhitched", "09"), ("formed", OWN), ("started", OWN)])
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07", "11"])

    def test_the_alone_rule_and_what_never_rides(self):
        self.crop("07", {".github/workflows/merge-to-main.yml": "on: push\n"})
        self.crop("09", {"nine.txt": "9"})
        self.crop("31", {"servant.txt": "s"})
        self.gate.ticket("04", self.fields["07"], ready={"at": "2026-10-13T09:00:00Z", "by": "hal2/04",
                                                        "head": out(self.main, "rev-parse", "origin/main")})
        d = json.loads(self.call("train", "--dry-run", "--json")[1])
        self.assertEqual(([c["field"] for c in d["cars"]], d["alone"], d["waiting"]),
                         (["07"], True, [{"field": "09", "why": "rides in the next train, after the gate train"}]))
        self.round()
        self.assertEqual(self.last, [("unhitch", "run", "31"), ("unhitched", "relay", "31"), ("unhitch", "run", "04"),
                                     ("form", "run", "-")],
                         "31 has no session: its message waits as a relay; in the barn already: no message at all")
        self.assertEqual(self.gate.calls[-1], ["worktree", "queue", "train", OWN, "07"])
        self.assertTrue(self.gate.of("09")["ready"], "09 waits for the next train")
        self.assertEqual((self.gate.of("31"), self.gate.of("04")), (None, None))

    def test_a_car_that_does_not_merge_or_a_refused_mark_breaks_the_train_up_again(self):
        self.crop("07", {"seven.txt": "7"})
        base, head = out(self.wm, "rev-parse", "HEAD"), self.gate.of("07")["ready"]["head"]
        car = {"field": "07", "branch": "07", "head": head, "plan": ""}
        self.gate.refuse = "07"  # the mark with this car
        code, text = engine.form(str(self.wm), [car])
        self.assertEqual(code, 1, text)
        self.assertIn("was not marked: refused: 07", text)
        self.assertEqual((out(self.wm, "rev-parse", "HEAD"), self.spawned, self.train()), (base, [], None))
        self.assertFalse((self.wm / "plans/CURRENT_PLAN").exists())
        self.assertEqual(self.state(), [("formed", OWN), ("cleared", OWN)])
        self.gate.refuse = ""
        code, text = engine.form(str(self.wm), [dict(car, head="0" * 40)])
        self.assertEqual((code, out(self.wm, "rev-parse", "HEAD"), self.train()), (1, base, None), text)
        self.assertEqual(engine.form(str(self.wm), [])[0], 1)
        r = self.round()  # the tick's own form of the same car now works; a failed run would wake the session
        self.assertEqual((self.last, r["wake"], self.train()["state"]), ([("form", "run", "-")], [], "landing"))


class Standing(Farm):
    def setUp(self):
        super().setUp()
        self.crop("07", {"seven.txt": "7"}, plan="0294-wagon-master-role")
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
        last = train_state.lines(str(self.main))[-1]
        self.assertEqual((last["kind"], last["cars"], last["run"], last["commit"]),
                         ("landed", ["07", "09"], "https://github.com/x/runs/9", "c0ffee"))
        self.assertIsNone(tick.slot_problem(str(self.wm), wagon_master.WIRING), "between trains: the frame's own check")
        r = self.round()
        self.assertEqual((self.last, [a["kind"] for a in r["planned"] if a["duty"] == "frame"]), ([], ["stay-current"]))
        self.assertEqual(len(self.typed), 2, "nobody is told twice")

    def test_red_wakes_the_session_once_and_unhitch_lets_the_rest_form_again(self):
        self.ends({"status": "gate_failed", "run": "https://github.com/x/runs/9", "red": [{"name": "linux / rust-test"}]})
        self.gate.of(OWN).update(state="held", train=None, hold={"reason": "failed"})  # the landing's end
        r = self.round()
        self.assertEqual(self.last, [("red", "run", "-"), ("train-failed", "wake", "-")])
        (wake,) = r["wake"]
        for part in ("did not land (gate_failed): linux / rust-test", "Run: https://github.com/x/runs/9.",
                     "Cars: 07 (0294-wagon-master-role), 09 (09)."):
            self.assertIn(part, wake["text"])
        self.assertEqual(self.call("act")[1].count(str(SKILL / "instructions/trains.md")), 1)
        self.round()
        self.assertEqual((self.last, self.train()["state"], self.spawned), ([], "red", [OWN]), "nothing else")

        # 2026-10-14: unhitched at 12:53:36, broken up by the next round at 12:57:10 (plan 0333 step 6, cause C);
        # now the unhitch's own call breaks the train up, tells 09's foreman and forms the rest.
        self.panes = {"09": "%9"}
        code, text = self.call("unhitch", "09", "--why", "its test fails", repo=self.main)
        self.assertEqual((code, text), (0, "09 unhitched: its test fails; the rest of the train forms again\n"
                                           "chain link 1: breakup -, unhitched 09, form -\n"
                                           "chain stops: a landing started\n"))
        self.assertIsNone(self.gate.of("09"))
        self.assertIn("field 09 is unhitched from the red train: its test fails. Fix it, push and report it ready "
                      "again (`hal2-cli-git worktree queue ready`).", self.typed[0][1])
        self.assertIn(["worktree", "release", OWN], self.gate.calls, "its own failed landing's hold")
        self.assertEqual(self.gate.calls[-1], ["worktree", "queue", "train", OWN, "07"])
        self.assertEqual(self.subjects(), ["Merge branch '07' into wagon-master-hal2", "seven.txt"])
        self.assertEqual(self.state()[-5:], [("red", OWN), ("unhitched", "09"), ("cleared", OWN), ("formed", OWN),
                                             ("started", OWN)])
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
        self.assertEqual(self.state()[-3:], [("landed", OWN), ("formed", OWN), ("started", OWN)])
        self.assertEqual((self.gate.calls[-1], len(self.spawned)), (["worktree", "queue", "train", OWN, "11"], 2))
        self.assertEqual(([c["field"] for c in self.train()["cars"]], self.subjects()),
                         (["11"], ["Merge branch '11' into wagon-master-hal2", "eleven.txt"]))
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
        head = out(self.wm, "rev-parse", "HEAD")
        self.assertEqual(self.call("retry", "--why", "flaky: tmux_attach")[0], 0)
        self.round()
        self.assertEqual((self.last, self.train()["state"], self.train()["starts"]), ([("restart", "run", "-")], "landing", 2))
        self.assertEqual((out(self.wm, "rev-parse", "HEAD^"), len(self.spawned)), (head, 2),
                         "the train as it is, one empty commit on it: a new candidate, a fresh run (plan 0313 step 13)")
        self.assertEqual(self.gate.calls[-1], ["worktree", "queue", "train", OWN, "07", "09"], "marked before every start")

    def test_an_interrupted_landing_is_started_again_and_adopts_its_run(self):
        self.ends(None)  # the process gone without a word
        self.round()
        self.assertEqual((self.last, self.train()["starts"], self.spawned), ([("restart", "run", "-")], 2, [OWN] * 2))
        self.alive.add(40002)
        self.round()
        self.assertEqual(self.last, [])
        self.ends({"status": "interrupted", "message": "the process that started merge-to-main is gone"})
        self.round()
        self.assertEqual((self.last, self.train()["starts"]), ([("restart", "run", "-")], 3))
        self.assertEqual([k for k, _ in self.state()], ["formed", "started", "started", "started"])

    def test_a_leftover_mark_is_cleared_and_the_round_starts_from_the_ready_tickets(self):
        self.alive.clear()
        (self.wm_state / train_state.FILE).unlink()  # the wagon master's state is gone, its field new
        git(self.wm, "reset", "-q", "--hard", self.base)
        (self.wm / "plans/CURRENT_PLAN").unlink()
        self.gate.calls.clear()
        self.round()
        self.assertEqual(self.last, [("breakup", "run", "-"), ("form", "run", "-")])
        self.assertEqual(self.gate.calls, [["worktree", "queue", "train", OWN, "--clear"],
                                           ["worktree", "queue", "train", OWN, "07", "09"]])
        self.assertEqual(self.state(), [("cleared", OWN), ("formed", OWN), ("started", OWN)])
        self.assertEqual(train_state.lines(str(self.main))[0]["why"], "a mark without a train of ours")


class Files(Farm):
    def test_the_state_is_of_the_kinds_the_manifest_declares(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"seven.txt": "nine"})
        self.round()
        self.ends({"status": "gate_failed", "run": "https://github.com/x/runs/9"})
        self.round()
        self.call("retry", "--why", "flaky")
        self.round()
        self.ends({"status": "landed", "commit": "c0ffee"}, land=True)
        self.round()
        lines = train_state.lines(str(self.main))
        self.assertEqual([e["kind"] for e in lines], ["unhitched", "formed", "started", "red", "retry", "started", "landed"])
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
            f.write(json.dumps({"schema": 1, "at": train_state.utc(), "kind": "derailed", "slot": OWN}) + "\n")
        p = subprocess.run([checker, "check", str(self.wm_state), "--manifest", str(SKILL / "manifest.toml"), "--json"],
                           capture_output=True, text=True)
        self.assertEqual([(x["path"].rsplit("/", 1)[-1], x["line"]) for x in json.loads(p.stdout)["problems"]],
                         [(train_state.FILE, 8)], p.stdout)
        self.assertRaises(ValueError, train_state.append, str(self.main), "derailed", OWN)

    def test_the_landing_is_a_child_of_a_process_that_stays(self):
        with mock.patch.object(engine, "LAND", [sys.executable, "-c", "import sys; sys.exit(4)"]):
            self.assertEqual(engine.land(str(self.wm)), 4)
        self.assertEqual(engine.LAND, ["hal2-cli-git", "worktree", "merge-to-main", "--json"])


class Spawn(unittest.TestCase):
    def test_the_detached_start(self):
        import tempfile
        log = Path(tempfile.mkdtemp()) / "train-landing.log"
        with mock.patch.object(engine.subprocess, "Popen") as popen:
            popen.return_value.pid = 4711
            self.assertEqual(engine.spawn("/farm/wagon-master-hal2", log), 4711)
        (argv,), kw = popen.call_args
        self.assertEqual(argv, [sys.executable, str(trains.ENGINE), "land", "--repo", "/farm/wagon-master-hal2"])
        self.assertEqual((kw["cwd"], kw["start_new_session"], kw["stdin"], kw["stderr"], kw["stdout"].name),
                         ("/farm/wagon-master-hal2", True, subprocess.DEVNULL, subprocess.STDOUT, str(log)))


if __name__ == "__main__":
    unittest.main()
