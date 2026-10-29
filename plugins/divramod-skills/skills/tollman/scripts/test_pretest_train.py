"""Hal2 plan 0349 step 28 (D75): the train's pretest (pretest_train.py) on engine_farm.py's farm with the stub gate
(pretest_stub.py): a red pretest stops the landing before merge-to-main starts and wakes the session with the job and
its car; `retry` pretests again, `retry --skip-pretest` lands without it; a red stays red whatever breaks after it."""

import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import local_load
import pretest
import pretest_train
import train_state
from engine_farm import Farm
from pretest_stub import Stub, config

os.environ.setdefault("HAL2_WORKQUEUE_FREEZE", "0")  # no test takes a real workqueue hold (plan 0466)

SKILL = Path(__file__).resolve().parents[1]


def probes():
    """The fake machine: 20 s, load 3.0 then 7.5, 1000 more disk operations."""
    yield {"at": 0.0, "utc": "2026-10-29T10:00:00Z", "load1": 3.0, "ops": 5000}
    yield {"at": 20.0, "utc": "2026-10-29T10:00:20Z", "load1": 7.5, "ops": 6000}



class Landing(Farm):
    """The engine's side: `engine.py land` pretests the train that stands before merge-to-main starts."""

    def setUp(self):
        super().setUp()
        self.probes = probes()
        self.stub = Stub(self.tmp / "gate")
        for p in (mock.patch.object(pretest, "GATE", str(self.stub.main)),
                  mock.patch.object(pretest, "salt", return_value="s"),
                  mock.patch.object(local_load, "probe", side_effect=lambda: next(self.probes)),
                  mock.patch.object(engine, "LAND", [sys.executable, "-c", "open(__import__('sys').argv[1], 'w')",
                                                     str(self.tmp / "landed")])):
            p.start()
            self.addCleanup(p.stop)
        self.crop("07", {"seven.txt": "7"}, plan="0294-tollman-role")
        self.crop("09", {"nine.txt": "9"})
        self.round()  # formed, landing started (spawn is the farm's fake)

    def land(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = engine.land(str(self.cw))
        return code, out.getvalue()

    def pretests(self):
        return [e for e in train_state.lines(str(self.main)) if e["kind"] == "pretest"]

    def roles_check(self):
        checker = next((str(Path(d) / "hal2-cli-roles") for d in os.environ.get("PATH", "").split(os.pathsep)
                        if (Path(d) / "hal2-cli-roles").is_file()), None)  # shutil.which is the fixture's fake
        if not checker:
            return []
        p = subprocess.run([checker, "check", str(self.wm_state), "--manifest", str(SKILL / "manifest.toml"), "--json"],
                           capture_output=True, text=True)
        # clean: the report on stdout; with problems exit 1 and the report in the error document's details
        if p.returncode == 0:
            return json.loads(p.stdout)["problems"]
        return json.loads(p.stderr)["error"]["details"]["problems"]

    def red(self):
        """A red pretest of python-lint, whose range is car 07's: the landing's result, settled as a red train."""
        config(self.cw / pretest.CONFIG, ["python-lint", "bash-lint"])
        self.stub.job("python-lint", "echo 'E501 line too long'; code=1")
        self.stub.selects(["python-lint"], head=self.gate.of("07")["ready"]["head"])
        self.stub.selects(["bash-lint"], head=self.gate.of("09")["ready"]["head"])
        code, out = self.land()
        self.assertEqual(code, 1)
        self.assertFalse((self.tmp / "landed").exists(), "merge-to-main never started: nothing pushed")
        result = json.loads(out.splitlines()[-1])
        self.ends(result)  # the landing's log holds what land printed; the tick settles it as a red train
        return result, self.round()

    def test_a_red_pretest_stops_the_push_and_names_the_car(self):
        result, r = self.red()
        log = str(self.wm_state / pretest_train.LOG)
        self.assertEqual(result, {"status": "pretest_red", "red": [{"name": "python-lint", "log": log}],
                                  "suspects": ["07"], "message": "pretest: python-lint red, car 07"})
        self.assertIn("E501 line too long", Path(log).read_text())
        (line,) = self.pretests()
        self.assertEqual((line["slot"], line["result"], [j["job"] for j in line["jobs"]]),
                         (self.carrier(), "red", ["python-lint", "bash-lint"]))
        self.assertEqual(self.roles_check(), [], "the pretest line, its log and its markers as the manifest declares")
        self.assertEqual(self.last, [("red", "run", "-"), ("train-failed", "wake", "-")])
        (wake,) = r["wake"]
        self.assertIn("did not land (pretest_red): python-lint, suspects: 07.", wake["text"])
        self.round()
        self.assertEqual((self.last, self.train()["state"]), ([], "red"), "pretest_red never restarts by itself")

        self.call("retry", "--why", "fixed by hand")  # the session's word: the pretest runs again, a red is not kept
        self.round()
        self.stub.job("python-lint", "code=0")
        code, out = self.land()
        self.assertEqual((code, [e["result"] for e in self.pretests()]), (0, ["red", "green"]))
        self.assertTrue((self.tmp / "landed").exists())

    def test_retry_skip_pretest_lands_a_train_whose_red_is_the_macs(self):
        self.red()
        code, text = self.call("retry", "--skip-pretest", "--why", "fails on this Mac only")
        self.assertEqual((code, text.strip()), (0, f"train {self.train()['train']} lands again at the next round "
                                                   "without its pretest: fails on this Mac only"))
        self.assertEqual((self.pretests()[-1]["result"], self.pretests()[-1]["why"]),
                         ("skipped", "skipped by the session: fails on this Mac only"))
        self.round()
        ran = len(self.stub.ran())
        code, out = self.land()
        self.assertEqual((code, len(self.stub.ran()), len(self.pretests())), (0, ran, 2), "no pretest ran")
        self.assertTrue((self.tmp / "landed").exists())
        self.assertEqual(self.roles_check(), [])

    def test_a_red_known_before_a_failure_still_stops_the_push(self):
        config(self.cw / pretest.CONFIG, ["python-lint"])
        self.stub.job("python-lint", "code=1")
        with mock.patch.object(pretest, "write_log", side_effect=ValueError("broken after the jobs")):
            code, out = self.land()
        result = json.loads(out.splitlines()[-1])
        self.assertEqual((code, result["status"], result["red"][0]["name"]), (1, "pretest_red", "python-lint"))
        self.assertFalse((self.tmp / "landed").exists())
        self.assertIn("the pretest broke: broken after the jobs", self.pretests()[0]["why"])

    def test_a_pretest_that_breaks_before_any_red_never_holds_the_train(self):
        config(self.cw / pretest.CONFIG, ["python-lint"])
        with mock.patch.object(pretest, "plan", side_effect=KeyError("bug")):
            code, out = self.land()
        self.assertEqual((code, self.pretests()[0]["result"]), (0, "skipped"))
        self.assertTrue((self.tmp / "landed").exists())

    def test_without_a_config_the_landing_goes_on_and_a_green_train_is_not_pretested_again(self):
        code, out = self.land()
        self.assertEqual(code, 0)
        self.assertRegex(out.strip(), r"^pretest: none in [\d.]+ s \(no \.github/hal2-pretest\.toml\)$")
        self.assertTrue((self.tmp / "landed").exists())
        self.assertEqual([e["result"] for e in self.pretests()], ["none"])
        config(self.cw / pretest.CONFIG, ["python-lint"])
        self.assertEqual(self.land()[0], 0, "a restart of the same train adopts its landing")
        self.assertEqual((len(self.pretests()), self.stub.calls()), (1, []))

    def test_the_pretest_line_carries_what_the_local_phase_cost(self):
        self.assertEqual(self.land()[0], 0)
        (line,) = self.pretests()
        self.assertEqual(self.roles_check(), [], "the `local` key as the manifest's schema declares it")
        local = line["local"]
        self.assertEqual([m["t"] for m in local["marks"]], ["start", "end"])
        self.assertEqual((local["seconds"], local["load_peak"], local["disk_ops_s"]), (20.0, 7.5, 50.0))
        self.assertEqual(local["marks"][1]["ops_s"], 50.0)

    def test_no_train_no_pretest(self):
        self.assertEqual(engine.breakup(str(self.wm), "test", user=True)[0], 0)
        self.assertFalse(pretest_train.before_landing(str(self.wm)))
        self.assertEqual(len(self.pretests()), 0)


class Blame(unittest.TestCase):
    TRAIN = {"cars": [{"field": "07", "head": "a"}, {"field": "09", "head": "b"}]}

    def blame(self, **patch):
        with mock.patch.object(pretest, "git", return_value="base"), mock.patch.object(pretest, "plan", **patch):
            return pretest_train.blame("/nowhere", self.TRAIN, "python-lint", "origin/main", yard="c0ffee")

    def test_the_cars_whose_range_selects_the_job(self):
        self.assertEqual(self.blame(side_effect=lambda top, gate, start, head, left: {"python-lint": {}}
                                    if head == "b" else {}), ["09"])

    def test_every_car_when_none_selects_it_or_the_gate_does_not_answer_in_time(self):
        every = ["07", "09", "yard"]
        self.assertEqual(self.blame(return_value={}), every)
        self.assertEqual(self.blame(side_effect=subprocess.TimeoutExpired("gate", 1)), every)
        self.assertEqual(self.blame(side_effect=RuntimeError("gate plan ended 1")), every)
        with mock.patch.object(pretest_train, "BLAME_SECONDS", 0):
            self.assertEqual(self.blame(return_value={"python-lint": {}}), every, "out of time: not every car looked")


class Sigterm(unittest.TestCase):
    def test_sigterm_raises_systemexit_while_the_pretest_runs(self):
        before = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(SystemExit) as stopped, pretest_train.sigterm_exits():
            os.kill(os.getpid(), signal.SIGTERM)
        self.assertEqual((stopped.exception.code, signal.getsignal(signal.SIGTERM)), (128 + signal.SIGTERM, before))


if __name__ == "__main__":
    unittest.main()
