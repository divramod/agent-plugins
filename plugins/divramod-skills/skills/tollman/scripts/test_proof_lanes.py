"""Hal2 plan 0490 step 7: a car's lane moves (proof_lanes.py), replaying learnings L70 (train 11: a lane moved to az02,
which the barn's runner list lacked, queued for good), L83 and L87 (train 13: reds on the runner car 03 newly routed
to, named no car) and L86 (train 13-4: rust-test 60+ minutes on az03 against 18 on hz01). `git show` and `gh` are
faked; `moved_by` runs over a real temporary repository."""

import datetime as dt
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import proof
import proof_lanes as pl

WF = ".github/workflows/merge-to-main-cloud.yml"
HZ01_A = "[self-hosted, linux, x64, hz01-host-a]"
AZ02_A = "[self-hosted, linux, x64, az02-host-a]"


def workflow(b1: str, c3: str = "[self-hosted, linux, x64, hz01-host-b]", e4: str = "") -> str:
    e4 = e4 or "[self-hosted, linux, x64, hz01-host-c]"
    return (f"name: x\non:\n  push:\njobs:\n  a1-mac-host-hal2-a:\n    runs-on: [self-hosted, macOS, ARM64, mac-host-hal2-a]\n"
            f"  b1-{b1.strip('[]').split(', ')[-1]}:\n    name: b1-${{{{ matrix.pos }}}}\n    needs: a1-mac-host-hal2-a\n"
            f"    runs-on: {b1}\n  c3-{c3.strip('[]').split(', ')[-1]}:\n    runs-on: {c3}\n"
            f"  e4-x:\n    runs-on: {e4}\n  lint:\n    runs-on: ubuntu-latest\n")


RUNNERS = ('[[runners]]\ncode = "hz01-host-a"\nlabels = ["self-hosted", "linux", "x64", "hz01-host-a"]\n'
           '[[runners]]\ncode = "hz01-host-b"\nlabels = ["self-hosted", "linux", "x64", "hz01-host-b"]\n'
           '[[runners]]\ncode = "hz01-host-c"\nlabels = ["self-hosted", "linux", "x64", "hz01-host-c"]\n'
           '[[runners]]\ncode = "mac-host-hal2-a"\nlabels = ["self-hosted", "macOS", "ARM64", "mac-host-hal2-a"]\n')


def github(*runners: tuple[str, str]) -> str:
    return json.dumps({"runners": [{"name": n, "status": s, "labels": [{"name": x} for x in
                                    ("self-hosted", "Linux", "X64", n)]} for n, s in runners]})


class Fake:
    """`run` over trees by rev ({rev: {path: text}}) and one GitHub answer; counts the gh calls."""

    def __init__(self, trees, gh=(1, "")):
        self.trees, self.gh, self.calls = trees, gh, []

    def __call__(self, argv, cwd):
        if argv[0] == "gh":
            self.calls.append(argv)
            return self.gh
        rev, path = argv[2].split(":", 1)
        text = self.trees.get(rev, {}).get(path)
        return (0, text) if text is not None else (128, "fatal")


def check(head_wf: str, gh=(1, ""), runners=RUNNERS):
    fake = Fake({"main": {WF: workflow(HZ01_A), pl.RUNNERS: runners}, "h": {WF: head_wf}}, gh)
    return pl.check("/f", "main", "h", [WF, "code/x.rs"], fake), fake


class Lanes(unittest.TestCase):
    def test_hal2s_own_workflow_parses_by_stage(self):
        root = next(p for p in Path(__file__).resolve().parents if (p / ".github/workflows").is_dir())
        got = pl.lanes((root / WF).read_text())
        for stage in ("a1", "b1", "c2", "c3", "d1", "e4", "f1"):
            self.assertIn(stage, got)
            self.assertTrue(all("self-hosted" in s for s in got[stage]), stage)

    def test_forms_of_runs_on(self):
        text = ("jobs:\n  x:\n    runs-on:\n      - self-hosted\n      - Linux\n  y:\n    runs-on: ${{ matrix.os }}\n"
                "  z:\n    runs-on: 'ubuntu-latest'  # hosted\n")
        self.assertEqual(pl.lanes(text), {"x": {frozenset({"self-hosted", "linux"})}, "z": {frozenset({"ubuntu-latest"})}})

    def test_a_moved_lane_keeps_its_stage_and_the_old_labels(self):
        fake = Fake({"b": {WF: workflow(HZ01_A)}, "h": {WF: workflow(AZ02_A)}})
        got = pl.moves("/f", "b", "h", [WF], fake)
        self.assertEqual(got, [{"workflow": WF, "job": "b1", "from": sorted(["self-hosted", "linux", "x64", "hz01-host-a"]),
                                "to": sorted(["self-hosted", "linux", "x64", "az02-host-a"])}])


class L70(unittest.TestCase):
    def test_train_11_a_lane_moved_to_az02_the_barn_lacks_and_offline_is_red(self):
        (code, text), fake = check(workflow(AZ02_A), gh=(0, github(("az02-host-a", "offline"))))
        self.assertEqual(code, 1)
        self.assertTrue(text.startswith(f"{WF}: job b1 moves runs-on to [az02-host-a, linux, self-hosted, x64]"), text)
        self.assertIn("(L70)", text)
        self.assertEqual(len(fake.calls), 1)

    def test_the_same_move_rides_when_the_runner_is_online(self):
        (code, _), _ = check(workflow(AZ02_A), gh=(0, github(("az02-host-a", "online"))))
        self.assertEqual(code, 0)

    def test_a_runner_in_the_barns_list_rides_without_asking_github(self):
        listed = RUNNERS + '[[runners]]\ncode = "az02-host-a"\nlabels = ["self-hosted", "linux", "x64", "az02-host-a"]\n'
        (code, _), fake = check(workflow(AZ02_A), runners=listed)
        self.assertEqual((code, fake.calls), (0, []))

    def test_no_move_asks_nothing_and_github_silent_skips(self):
        (code, _), fake = check(workflow(HZ01_A))
        self.assertEqual((code, fake.calls), (0, []))
        (code, _), _ = check(workflow(AZ02_A), gh=(1, ""))
        self.assertEqual(code, 127, "GitHub silent: the check cannot run, never red")

    def test_a_hosted_job_and_a_barn_without_a_runner_list_are_not_judged(self):
        (code, _), _ = check(workflow(HZ01_A).replace("ubuntu-latest", "windows-latest"))
        self.assertEqual(code, 0)
        (code, _), _ = check(workflow(AZ02_A), runners="")
        self.assertEqual(code, 127)


class Moved(unittest.TestCase):
    """L83, L87: train 13's reds on az02 (python-test FileNotFoundError hal2-cli-secrets; post-merge e4-01-hub-deploy)
    belong to car 03, which moved those lanes; a red on a lane nobody moved names no car."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.g("init", "-q", "-b", "main")
        self.base = self.commit(workflow(HZ01_A))
        self.g("checkout", "-q", "-b", "03")
        self.head = self.commit(workflow(HZ01_A, c3="[self-hosted, linux, x64, az02-host-a]", e4=AZ02_A))
        self.g("checkout", "-q", "-b", "05", self.base)
        self.other = self.commit(workflow(HZ01_A), extra=True)

    def g(self, *a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.d, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, text, extra=False):
        (Path(self.d) / WF).parent.mkdir(parents=True, exist_ok=True)
        (Path(self.d) / WF).write_text(text)
        if extra:
            (Path(self.d) / "a.rs").write_text("a\n")
        self.g("add", "-A")
        self.g("commit", "-q", "-m", "x")
        return self.g("rev-parse", "HEAD")

    def test_train_13_reds_on_the_moved_lanes_are_car_03s(self):
        moved = pl.moved_by(self.d, self.base, [{"field": "03", "head": self.head}, {"field": "05", "head": self.other}],
                            proof.sh)
        self.assertEqual(sorted(moved), ["03"])
        self.assertEqual(pl.mover("c3-02-python-test", moved), ["03"])
        self.assertEqual(pl.mover("e4-01-hub-deploy", moved), ["03"], "L87: the delivery red is the mover's too")
        self.assertEqual(pl.mover("b1-01-ci-changes", moved), [])


class L86(unittest.TestCase):
    NOW = dt.datetime(2026, 10, 24, 1, 0, tzinfo=dt.timezone.utc)
    MOVED = {"03": [{"workflow": WF, "job": "c3", "from": [], "to": ["az03-host-b"]}]}

    def job(self, name, start, end=None, conclusion=None, runner=""):
        return {"name": name, "started_at": start, "completed_at": end, "conclusion": conclusion, "runner_name": runner}

    def test_train_13_4_rust_test_on_az03_over_twice_its_green_time_is_flagged(self):
        green = [self.job("c3-01-rust-test", "2026-10-23T20:00:00Z", "2026-10-23T20:18:00Z", "success")]
        now = [self.job("c3-01-rust-test", "2026-10-23T23:55:00Z", "2026-10-24T00:56:00Z", "success", "az03-host-b"),
               self.job("c2-01-ts-test", "2026-10-23T23:55:00Z", "2026-10-24T00:56:00Z", "success")]
        got = pl.slow(self.MOVED, now, green, self.NOW)
        self.assertEqual(got, [{"job": "c3-01-rust-test", "cars": ["03"], "runner": "az03-host-b", "secs": 3660,
                                "green_secs": 1080}])

    def test_a_running_job_counts_its_time_so_far_and_within_twice_is_not_flagged(self):
        green = [self.job("c3-01-rust-test", "2026-10-23T20:00:00Z", "2026-10-23T20:18:00Z", "success")]
        running = [self.job("c3-01-rust-test", "2026-10-24T00:20:00Z")]
        self.assertEqual(len(pl.slow(self.MOVED, running, green, self.NOW)), 1, "40 minutes so far against 18")
        quick = [self.job("c3-01-rust-test", "2026-10-24T00:30:00Z")]
        self.assertEqual(pl.slow(self.MOVED, quick, green, self.NOW), [], "30 minutes is within twice 18")


if __name__ == "__main__":
    unittest.main()
