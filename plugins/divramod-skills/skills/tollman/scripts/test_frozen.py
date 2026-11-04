"""Hal2 plan 0490 step 20 (D20, D21, D23; open-train-brief.md 1), plan 0610 D17 (E4-E6, E8, E10): the open train in
its landing. The next train forms on the green merge job of the train before; while its landing's process waits for
that run, and once more right before the push, every newly hitched wagon joins it (open_train.py: merged into the
carrier, a `joined` line, the mark refreshed), a conflict with its resolve order and a red pretest with its fix order;
after the push nothing joins. Nothing ever leaves the train (frozen.py, plan 0360 D3) and nothing is declined. On
test_next_train's farm (a bare origin, gh_fake.py's runs); the pretest of a joining car on pretest_stub.py's gate."""
# enforces .adr/merge-queue-policy.md and .adr/tollman.md

import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import next_train
import open_train
import train_state
import trains
from engine_farm import out
from pretest_stub import FieldCase, config, sh
from test_farmer import git
from test_next_train import Trains

GREEN = {"state": "green", "lines": []}


class OpenTrain(Trains):
    """Train A (20+02) merged green, its run 720 runs on; train B (03) formed on the new main and waits for it."""

    def setUp(self):
        super().setUp()
        proven = mock.patch.object(trains, "PROVE", lambda *a: GREEN)
        proven.start()
        self.addCleanup(proven.stop)
        self.crop("03", {"three.txt": "3"}, plan="0382-three")
        self.merged()
        self.minute()
        self.b = self.train()
        self.assertEqual(([c["field"] for c in self.b["cars"]], self.b["state"]), (["03"], "landing"))

    def wait(self, polls=1):
        """The landing's wait (next_train.before_push): run 720 concludes after `polls` sleeps; the lines."""
        naps = []

        def sleep(_):
            naps.append(1)
            if len(naps) >= polls:
                self.gh.runs[0] = dict(self.run, status="completed", conclusion="success")

        with contextlib.redirect_stdout(io.StringIO()):
            return next_train.before_push(str(self.cw), sleep=sleep)

    def cars(self):
        return [c["field"] for c in self.train()["cars"]]

    def test_a_wagon_hitched_during_the_wait_joins_the_train(self):
        four = self.crop("04", {"four.txt": "4"}, plan="0384-four")
        before = out(self.cw, "rev-parse", "HEAD")
        lines = self.wait()
        self.assertTrue(lines[1].startswith(f"open train {self.b['train']}: field 04 (0384-four) joined, pretest none"),
                        lines)
        self.assertEqual((self.cars(), self.train()["state"], self.train()["train"]),
                         (["03", "04"], "landing", self.b["train"]), "the same train, one car more")
        self.assertEqual(out(self.cw, "rev-parse", "HEAD^1"), before)
        self.assertEqual(out(self.cw, "rev-parse", "HEAD^2"), four["ready"]["head"], "merged into the carrier")
        joined = train_state.lines(str(self.main))[-1]
        self.assertEqual((joined["kind"], joined["base"], joined["commit"]),
                         ("joined", before, out(self.cw, "rev-parse", "HEAD")))
        mark = self.gate.of(self.carrier())["train"]
        self.assertLessEqual({"03", "04"}, {c["field"] for c in mark["cars"]}, "the queue's mark refreshed")
        self.assertIn("--attempt", next(c for c in self.gate.calls if "04" in c), "the start that runs, its branch")
        self.assertTrue(mark.get("pid"), "the landing's pid stamped again (marking replaces the mark)")
        self.assertIn("0384-four", self.pointer(), "the land run's title")
        self.assertEqual(self.wait(), [], "the run before has concluded: no wait, nothing joins")

    def pointer(self):
        return open_train.frozen.POINTERS.read(str(self.cw), open_train.frozen.CURRENT) or ""

    def test_a_wagon_hitched_after_the_run_before_concluded_joins_before_the_push(self):
        # plan 0610 E4, D17: the join round runs once more right before the push, also with no run before
        self.gh.runs[0] = dict(self.run, status="completed", conclusion="success")
        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        lines = self.wait()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("field 04 (0384-four) joined", lines[0])
        self.assertEqual((self.cars(), open_train.stops(str(self.cw))), (["03", "04"], 0), "the push goes with it")

    def test_after_the_push_a_wagon_rides_the_next_train(self):
        train_state.append(str(self.main), "push", self.carrier(), train=self.b["train"],
                           head=out(self.cw, "rev-parse", "HEAD"))
        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        self.assertEqual(open_train.take(str(self.cw), str(self.main)), [], "its push started: no join")
        self.assertEqual(self.cars(), ["03"])

    def test_a_conflicting_wagon_joins_with_its_resolve_order_and_the_push_waits(self):
        # plan 0610 E5, E6: never declined; a proof `wait` rides with `proof_unknown` (E16)
        self.crop("04", {"three.txt": "four"}, plan="0384-four")  # conflicts with 03 in three.txt
        self.crop("05", {"five.txt": "5"}, plan="0385-five")
        before = out(self.cw, "rev-parse", "HEAD")
        with mock.patch.object(trains, "PROVE", lambda main, field, head, barn: GREEN if "04" in field else {
                "state": "wait", "lines": ["no proof yet"]}):
            lines = self.wait(polls=2)
        t = self.train()
        self.assertIn("field 04 (0384-four) joined with a conflict, the push waits for its resolve", lines[-1])
        self.assertEqual((self.cars(), t["state"], t["resolve"]["field"], out(self.cw, "rev-parse", "HEAD")),
                         (["03", "04"], "resolving", "04", before), "the carrier as before: 04 waits for its resolve")
        self.assertNotIn("declined", [k for k, _ in self.state()])
        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet):
            self.assertEqual(open_train.stops(str(self.cw)), 1, "no push while it waits")
        self.assertIn("is resolving: a car that joined waits for its resolve", quiet.getvalue())
        self.round()  # outside the landing the round's join records 05 (plan 0610 D17)
        self.assertEqual((self.cars(), self.train()["state"]), (["03", "04", "05"], "resolving"))

    def test_a_red_pretest_joins_with_its_fix_order_and_the_push_waits(self):
        # plan 0610 E6: the car stays merged, rides with `pretest_red`; the push makes the train red first
        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        red = {"result": "red", "seconds": 1, "jobs": [{"job": "python-lint", "result": "red"}], "why": "", "log": "l"}
        with mock.patch.object(open_train, "check", return_value=red) as check:
            lines = self.wait(polls=2)
        car = self.train()["cars"][-1]
        self.assertEqual((check.call_count, self.cars(), out(self.cw, "rev-parse", "HEAD^2")),
                         (1, ["03", "04"], self.gate.of("04")["ready"]["head"]), "merged, never put back")
        self.assertIn("field 04 (0384-four) joined, pretest red", lines[1])
        self.assertEqual((car["pretest_red"], car["proof_red"]), (["python-lint"], ["python-lint: its join pretest is red (l)"]))
        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet):
            self.assertEqual(open_train.stops(str(self.cw)), 1)
        t = self.train()
        self.assertEqual((t["state"], t["status"]), ("red", "proof_red"), quiet.getvalue())
        self.round()
        order = [e for e in train_state.lines(str(self.main)) if e["kind"] == "order"][-1]
        self.assertEqual((order["field"], order["jobs"], self.train()["state"]), ("04", ["python-lint"], "fixing"))

    def test_a_mark_the_queue_refuses_keeps_the_car_and_the_next_start_marks_it(self):
        # plan 0610 E6: a refused mark is no decline (hal2-cli-git refuses it once a push began, plan 0490 D24)
        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        calls = len(self.gate.calls)
        self.gate.refuse = "04"
        lines = self.wait()
        self.assertEqual((self.cars(), out(self.cw, "rev-parse", "HEAD^2")), (["03", "04"], self.gate.of("04")["ready"]["head"]))
        self.assertIn("field 04 (0384-four) joined, pretest none; the queue refused the mark (refused: 04)", lines[1])
        self.assertEqual([c for c in self.gate.calls[calls:] if "--pid" in c], [], "no stamp after a refused mark")
        self.assertEqual(train_state.lines(str(self.main))[-1]["mark"], "refused: 04")

    def test_a_riding_car_s_newer_head_joins_as_its_update(self):
        # plan 0610 E10: 03 hitched again on a newer head while its train waits
        path = self.fields["03"]
        (path / "three.txt").write_text("3, newer")
        git(path, "commit", "-qam", "three, newer")  # its own file only (plans/CURRENT_PLAN is the field's)
        git(path, "push", "-q", "origin", "HEAD")
        new = out(path, "rev-parse", "HEAD")
        self.gate.of("03")["ready"] = dict(self.gate.of("03")["ready"], head=new)
        lines = self.wait()
        self.assertIn("field 03 (0382-three) joined", lines[1])
        self.assertEqual((self.cars(), self.train()["cars"][0]["head"]), (["03"], new), "its car's place, its newer head")
        self.assertEqual(out(self.cw, "merge-base", "--is-ancestor", new, "HEAD"), "", "merged before the push")
        self.assertIn(f"Merge branch '03' into {self.branch()}", out(self.cw, "log", "-1", "--format=%s"))
        self.assertEqual(self.wait(), [], "once: the car is at its head now")

    def test_a_hand_merge_is_recorded_as_a_car(self):
        # plan 0610 E8, D8a: a head the tollman merged into the carrier by hand is a car (`carried`), proven no more
        four = self.crop("04", {"four.txt": "4"}, plan="0384-four")
        git(self.cw, "merge", "-q", "--no-ff", "-m", "by hand", four["ready"]["head"])
        head = out(self.cw, "rev-parse", "HEAD")
        with mock.patch.object(trains, "PROVE", side_effect=AssertionError("a carried head is never proven")):
            lines = self.wait()
        self.assertIn("field 04 (0384-four) joined", lines[1])
        self.assertEqual((self.cars(), self.train()["cars"][-1].get("carried"), out(self.cw, "rev-parse", "HEAD")),
                         (["03", "04"], True, head), "recorded, nothing merged again")
        self.assertIn("04", {c["field"] for c in self.gate.of(self.carrier())["train"]["cars"]}, "on the queue's mark")

    def test_a_train_whose_car_rides_alone_takes_nobody(self):
        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        with mock.patch.object(open_train.gate_car, "alone_why", lambda main, default, head: "it adds the workflow"):
            self.wait()
        self.assertEqual(self.cars(), ["03"])


class Fold(unittest.TestCase):
    def test_a_joined_car_counts_a_newer_head_takes_its_place_and_a_declined_head_is_read(self):
        rows = [{"kind": "formed", "train": "B", "cars": [{"field": "03"}]}, {"kind": "started", "train": "B", "pid": 1},
                {"kind": "joined", "train": "B", "cars": [{"field": "04"}]},
                {"kind": "declined", "train": "B", "field": "05", "head": "abc1234"}]
        b = train_state.standing(rows)
        self.assertEqual(([c["field"] for c in b["cars"]], b["state"], b["declined"]),
                         (["03", "04"], "landing", [{"field": "05", "head": "abc1234"}]))
        rows.append({"kind": "joined", "train": "B", "cars": [{"field": "03", "head": "newer"}]})  # plan 0610 E10
        self.assertEqual(train_state.standing(rows)["cars"], [{"field": "03", "head": "newer"}, {"field": "04"}])


class CarJobs(FieldCase):
    """open_train.check: the pretest after a join runs only the jobs the joining car's own range selects."""

    def test_only_the_new_car_s_jobs_run(self):
        barn = sh(self.top, "git", "rev-parse", "HEAD~1")
        sh(self.top, "git", "switch", "-q", "-c", "four", barn)
        (self.top / "four.txt").write_text("4\n")
        sh(self.top, "git", "add", "four.txt")
        sh(self.top, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "four")
        head = sh(self.top, "git", "rev-parse", "HEAD")
        sh(self.top, "git", "switch", "-q", "main")
        sh(self.top, "git", "-c", "user.name=t", "-c", "user.email=t@t", "merge", "-q", "--no-ff", "-m", "join", head)
        self.stub.selects(["bash-lint"], head=head)  # the car's range; the whole train's selects every job
        cfg = config(self.tmp / "hal2-pretest.toml", ["python-lint", "bash-lint"])
        r = open_train.check(str(self.top), self.state, barn, {"head": head}, cfg, self.stub.main)
        self.assertEqual((r["result"], self.states(r)),
                         ("green", [("python-lint", "not needed", None), ("bash-lint", "run", "green")]))
        self.assertEqual(self.stub.ran(), ["bash-lint"])

    def test_no_config_no_pretest_and_a_gate_that_cannot_say_skips(self):
        car = {"head": sh(self.top, "git", "rev-parse", "HEAD")}
        self.assertEqual(open_train.check(str(self.top), self.state, "HEAD~1", car, self.tmp / "none.toml",
                                          self.stub.main)["result"], "none")
        (self.stub.dir / "plan-builds").touch()  # the range needs the checkout's own CLI: no build (row 17)
        cfg = config(self.tmp / "hal2-pretest.toml", ["python-lint"])
        r = open_train.check(str(self.top), self.state, "HEAD~1", car, cfg, self.stub.main)
        self.assertEqual((r["result"], self.stub.ran()), ("skipped", []))
        self.assertIn("HAL2_GATE_NO_BUILD", r["why"])


if __name__ == "__main__":
    unittest.main()
