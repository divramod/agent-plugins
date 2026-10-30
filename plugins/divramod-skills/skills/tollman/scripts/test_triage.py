"""Hal2 plan 0360 step 5 (D5, D31): a red train is triaged as code when its landing ends. Three replays with fake gh
output (gh_fake.py): a runner fault is retried on a fresh run by code and wakes nobody; the barn's red (the same job
red in another slot's earlier run on the same barn head) wakes once with `main_red`; a car's red wakes once with
`car_red` and the evidence per car; a runner fault four times wakes once with `runner_broken`, the train still there."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import git_seed
import train_state
import trains
import triage
from gh_fake import FakeGh, job, run

AT = "2026-10-17T10:00:00Z"
NAME = "07+09@" + AT
URL = "https://github.com/x/actions/runs/601"
OURS = run(601, "land/tollman-hal2", "2026-10-17T10:06:00Z")
OTHER = run(590, "land/05", "2026-10-17T09:40:00Z", sha="c" * 40)  # field 05's red landing before the train
RED = {"status": "gate_failed", "run": URL, "red": [{"name": "d1-01-rust-test"}], "message": "the gate is red"}
MAIN_HEAD = "m" * 40


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def shape(actions):
    return [(a["kind"], a["do"]) for a in actions]


class Replays(unittest.TestCase):
    def grow(self):
        """The barn and the crops 07 and 09, grown once and shared by every process (git_seed)."""
        git(self.main, "init", "-q", "-b", "main")
        git(self.main, "config", "user.email", "t@t")
        git(self.main, "config", "user.name", "t")
        git(self.main, "commit", "-q", "--allow-empty", "-m", "base")
        base = git(self.main, "rev-parse", "HEAD")
        for field, f in (("07", "seven.txt"), ("09", "nine.txt")):
            git(self.main, "checkout", "-q", "-b", field, base)
            Path(self.main, f).write_text(field)
            git(self.main, "add", f)
            git(self.main, "commit", "-q", "-m", f)
        git(self.main, "checkout", "-q", "main")

    def setUp(self):
        """A barn and two cars: 07 changes seven.txt, 09 nine.txt (the evidence per car is a real diff)."""
        self.main = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.main, True)
        git_seed.guard(self)
        git_seed.grow(self.main, "test_triage.Replays", self.grow)
        base, *rest = git(self.main, "rev-parse", "main", "07", "09").split()
        heads = dict(zip(("07", "09"), rest))
        self.top = str(Path(self.main) / "tollman-hal2")
        self.train = {"train": NAME, "at": AT, "carrier": "tollman-hal2", "base": base, "state": "landing",
                      "starts": 1, "pid": 4711, "started": "2026-10-17T10:05:00Z", "unhitched": [], "yard": [],
                      "runner_retries": 0,
                      "cars": [{"field": "07", "branch": "07", "head": heads["07"], "plan": "0360-tollman-and-skills"},
                               {"field": "09", "branch": "09", "head": heads["09"], "plan": ""}]}
        for p in (mock.patch.object(triage, "main_head", lambda main: MAIN_HEAD),
                  mock.patch.object(triage.mtm_scan, "main_checkout", lambda top: self.main)):
            p.start()
            self.addCleanup(p.stop)

    def settle(self, gh, train=None):
        gh.start(self)
        return trains.settle(self.top, train or self.train, RED, {})

    def test_a_runner_fault_is_retried_by_code_on_a_fresh_run_and_wakes_nobody(self):
        gh = FakeGh([OURS, OTHER], jobs={"601": [job("d1-01-rust-test")]},
                    logs={"601": "d1-01-rust-test\tfetch\tnpm ERR! network read ECONNRESET\n"})
        out = self.settle(gh)
        self.assertEqual(shape(out), [("red", "run"), ("retry", "run"), ("restart", "run")])
        red, retry, restart = out
        self.assertEqual(red["argv"][2:8], ["red", "--status", "gate_failed", "--run", URL, "--why"])
        self.assertEqual(retry["argv"][2:5], ["retry", "--why", "runner: ECONNRESET"])
        self.assertEqual(restart["argv"][2], "restart")
        self.assertEqual((retry["after"], restart["after"]), (red["key"], retry["key"]))

    def test_the_barn_s_red_wakes_once_with_main_red(self):
        gh = FakeGh([OURS, OTHER], jobs={"601": [job("d1-01-rust-test")], "590": [job("d2-03-rust-test")]},
                    logs={"601": "assertion failed: tenant"}, parents={"c" * 40: [MAIN_HEAD, "5" * 40]})
        out = self.settle(gh)
        self.assertEqual(shape(out), [("red", "run"), ("train-failed", "wake")])
        wake = out[1]
        self.assertEqual((wake["key"], wake["after"], wake["evidence"]["kind"]), ("train-red:601", out[0]["key"], "main"))
        for part in (f"train {NAME} did not land (gate_failed)", "Triage: the barn is red, not a car", "rust-test",
                     "field 05", OTHER["url"], MAIN_HEAD[:12], "the train waits"):
            self.assertIn(part, wake["text"])
        other = FakeGh([OURS, OTHER], jobs=gh.jobs, logs=gh.logs, parents={"c" * 40: ["0" * 40]})
        self.assertEqual(self.settle(other)[1]["evidence"]["kind"], "car", "another barn head: not the barn's red")

    def test_a_car_s_red_wakes_once_with_car_red_and_the_evidence_per_car(self):
        gh = FakeGh([OURS, OTHER], jobs={"601": [job("d1-01-rust-test", step="cargo nextest")],
                                         "590": [job("d2-01-ts-test")]},
                    logs={"601": "test hub::tenant_rls ... FAILED\nthread panicked at seven.txt\n"})
        out = self.settle(gh)
        self.assertEqual(shape(out), [("red", "run"), ("train-failed", "wake")])
        wake = out[1]
        self.assertEqual((wake["key"], wake["evidence"]["kind"]), ("train-red:601", "car"))
        evidence = wake["evidence"]["evidence"]
        self.assertEqual(evidence["cars"], [{"field": "07", "files": ["seven.txt"]},
                                            {"field": "09", "files": ["nine.txt"]}])
        self.assertEqual((evidence["jobs"], evidence["tests"]), (["d1-01-rust-test: cargo nextest"], ["hub::tenant_rls"]))
        self.assertIn("thread panicked at seven.txt", evidence["tail"])
        for part in ("Triage: a car's red", "07: seven.txt", "09: nine.txt", "hub::tenant_rls",
                     "tollman.py triage 601"):
            self.assertIn(part, wake["text"])

    def test_a_runner_fault_four_times_wakes_once_and_the_train_stays(self):
        gh = FakeGh([OURS], jobs={"601": [job("d1-01-rust-test")]}, logs={"601": "Error: ETIMEDOUT"})
        out = self.settle(gh, dict(self.train, runner_retries=3))
        self.assertEqual(shape(out), [("red", "run"), ("train-runner-broken", "wake")])
        self.assertEqual(out[1]["key"], f"train-runner:{NAME}:3")
        self.assertIn("the runner looks broken: 3 runner faults in a row", out[1]["text"])
        rows = [{"schema": 1, "at": AT, "kind": "formed", "slot": "tollman-hal2", "train": NAME, "cars": [], "base": "b"}]
        for n in range(3):
            rows += [dict(rows[0], kind="started", pid=1), dict(rows[0], kind="red", status="gate_failed"),
                     dict(rows[0], kind="retry", why="runner: ETIMEDOUT")]
        self.assertEqual(train_state.standing(rows)["runner_retries"], 3)
        rows += [dict(rows[0], kind="retry", why="the barn is fixed")]
        self.assertEqual(train_state.standing(rows)["runner_retries"], 0, "in a row: another retry counts from 0")


class Classify(unittest.TestCase):
    def test_the_rules_as_data(self):
        red = [job("d1-01-rust-test")]
        self.assertEqual(triage.classify({"id": "1"}, red, "x 503 Service Unavailable y", {})["kind"], "runner")
        same = {"main": MAIN_HEAD, "other": {"slot": "05", "red": ["03-hz01-host-a/rust-test"], "parents": [MAIN_HEAD]}}
        self.assertEqual(triage.classify({"id": "1"}, red, "boom", same)["kind"], "main")
        self.assertEqual(triage.classify({"id": "1"}, red, "boom", dict(same, main=""))["kind"], "car")
        pauses = {**same, "pauses": [{"field": "03", "seq": 4, "run": "https://x/actions/runs/1"}]}
        cancelled = {"id": "1", "cancelled": True}
        self.assertEqual(triage.classify(cancelled, red, "ECONNRESET", pauses)["kind"], "none", "D59: no red")
        self.assertEqual(triage.classify({"id": "1"}, red, "boom", pauses)["kind"], "main", "not cancelled: red")
        smuggles = {**same, "smuggles": [{"slot": "05", "seq": 6, "files": ["code/a/tenant.rs"]}]}
        hit = triage.classify({"id": "1"}, red, "test hub::tenant ... FAILED", smuggles)
        self.assertEqual((hit["kind"], hit["evidence"]["slot"], hit["evidence"]["files"]),
                         ("smuggled", "05", ["code/a/tenant.rs"]), "D61: before main and car")


if __name__ == "__main__":
    unittest.main()
