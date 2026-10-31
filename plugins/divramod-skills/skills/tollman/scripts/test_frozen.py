"""Hal2 plan 0490 step 20 (D20, D21, D23; open-train-brief.md 1): the open train. The next train forms on the green
merge job of the train before; while its landing's process waits for that run, a newly hitched clean, proven wagon
joins it (open_train.py: merged into the carrier, a `joined` line, the mark refreshed); once the run before has
concluded its cars freeze and the push starts. Nothing ever leaves the train (frozen.py, plan 0360 D3). On
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

    def test_a_wagon_hitched_after_the_run_before_concluded_waits_for_the_next_train(self):
        self.gh.runs[0] = dict(self.run, status="completed", conclusion="success")  # the cars freeze, the push starts
        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        self.assertEqual(self.wait(), [], "no wait: the push is never delayed by a join (D9)")
        self.round()
        self.assertEqual(self.cars(), ["03"], "it waits for the next train")

    def test_a_dirty_or_unproven_wagon_waits(self):
        self.crop("04", {"three.txt": "four"}, plan="0384-four")  # conflicts with 03 in three.txt
        self.crop("05", {"five.txt": "5"}, plan="0385-five")
        with mock.patch.object(trains, "PROVE", lambda main, field, head, barn: GREEN if "04" in field else {
                "state": "wait", "lines": ["no proof yet"]}):
            lines = self.wait(polls=2)
        self.assertEqual(self.cars(), ["03"], lines)
        self.assertNotIn("declined", [k for k, _ in self.state()], "never tried: the draft left them out")

    def test_a_red_pretest_declines_the_car_once_and_puts_the_carrier_back(self):
        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        before = out(self.cw, "rev-parse", "HEAD")
        red = {"result": "red", "seconds": 1, "jobs": [{"job": "python-lint", "result": "red"}], "why": "", "log": "l"}
        with mock.patch.object(open_train, "check", return_value=red) as check:
            lines = self.wait(polls=2)
        self.assertEqual((check.call_count, self.cars(), out(self.cw, "rev-parse", "HEAD")), (1, ["03"], before))
        self.assertIn("field 04 waits for the next train: its pretest is red: python-lint", lines[1])
        self.assertEqual(self.train()["declined"][0]["field"], "04")

    def test_a_mark_the_queue_refuses_declines_the_car_and_puts_the_carrier_back(self):
        # hal2-cli-git refuses the mark once the carrier's landing began its push (plan 0490 row 24, D24).
        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        before, calls = out(self.cw, "rev-parse", "HEAD"), len(self.gate.calls)
        self.gate.refuse = "04"
        lines = self.wait()
        self.assertEqual((self.cars(), out(self.cw, "rev-parse", "HEAD")), (["03"], before))
        self.assertIn("field 04 waits for the next train: the queue refused the mark: refused: 04", lines[1])
        self.assertEqual([c for c in self.gate.calls[calls:] if "--pid" in c], [], "no stamp after a refused mark")
        self.assertEqual(self.train()["declined"][0]["field"], "04")

    def test_a_train_whose_car_rides_alone_takes_nobody(self):
        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        with mock.patch.object(open_train.gate_car, "alone_why", lambda main, default, head: "it adds the workflow"):
            self.wait()
        self.assertEqual(self.cars(), ["03"])


class Fold(unittest.TestCase):
    def test_a_joined_car_counts_and_a_declined_head_is_kept(self):
        rows = [{"kind": "formed", "train": "B", "cars": [{"field": "03"}]}, {"kind": "started", "train": "B", "pid": 1},
                {"kind": "joined", "train": "B", "cars": [{"field": "04"}]},
                {"kind": "declined", "train": "B", "field": "05", "head": "abc1234"}]
        b = train_state.standing(rows)
        self.assertEqual(([c["field"] for c in b["cars"]], b["state"], b["declined"]),
                         (["03", "04"], "landing", [{"field": "05", "head": "abc1234"}]))


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
