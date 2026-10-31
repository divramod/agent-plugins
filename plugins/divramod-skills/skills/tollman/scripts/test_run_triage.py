"""Hal2 plan 0490 step 1: the triage of a finished land run replays real runs (fixtures/run_triage: trimmed jobs and
failed-log lines of `gh run view <id> --json jobs` and `--log-failed`). Train 27's run 41009203691 against train
26's 40971471569 (its previous land run) and train 25's 40957447263 against train 23's green 40643116163: no red
goes to a car that did not cause it (L131), hub-deploy after the red stack-test is `needs-red`, a build-phase timeout
is `pipeline`, a failing spec goes to its owner field. Kinds no recorded run shows (runner, flake, car, unplaced)
replay a recorded unit with one line changed. The recheck recomputes from the evidence alone."""

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import run_triage
import run_triage_gather as gather
import run_triage_check as check
import run_triage_read as read

FIX = Path(__file__).with_name("fixtures") / "run_triage"
TRAINS = json.loads((FIX / "trains.json").read_text())
GRAPH = read.needs_graph((FIX / "workflow.yml").read_text())
GATE = {"hub-e2e", "web-e2e", "desktop-e2e", "stack-test", "rust-test"}
OCR, WQ = "e2e/electron/ocr.spec.ts", "e2e/electron/workqueue.spec.ts"


def recorded(n: str) -> tuple[dict, list[dict], str]:
    data = json.loads((FIX / f"train-{n}.jobs.json").read_text())
    return data, data["jobs"], (FIX / f"train-{n}.log").read_text()


def context(n: str, **kw) -> dict:
    t = TRAINS[n]
    ctx = {"graph": GRAPH, "cars": t["cars"], "owners": t["owners"], "paths": t["paths"], "live": set(),
           "plans": {}, "previous": [], "others": [], "gate_jobs": GATE, "dedup": {"orders": [], "wagons": []}}
    return {**ctx, **kw}


def triage(n: str, **kw) -> dict:
    data, jobs, log = recorded(n)
    run = {"id": data["url"].rsplit("/", 1)[1], "url": data["url"], "sha": data["headSha"], "base": TRAINS[n]["base"]}
    return {v["key"].split(":", 2)[2]: v for v in run_triage.triage(run, jobs, log, context(n, **kw))["verdicts"]}


def previous_26() -> list[dict]:
    _, jobs, log = recorded("26")
    return [{"id": "40971471569", "units": read.signatures(jobs, log)}]


class Train27(unittest.TestCase):
    """Train 27 (cars 02, 09, 21): the same reds as the trains before it, none of its cars'."""

    def test_no_car_gets_a_red(self):
        got = triage("27", previous=previous_26(), live={"02", "09", "21"})
        self.assertEqual(set(got), {"stack-test/hub-e2e", "stack-test/web-e2e", f"stack-test/desktop-e2e:{OCR}",
                                    f"stack-test/desktop-e2e:{WQ}", "runner-image-linux", "hub-deploy"})
        self.assertFalse({v["owner"] for v in got.values()} & {"02", "09", "21"})
        self.assertEqual(got["hub-deploy"]["kind"], "needs-red")
        self.assertEqual(got["hub-deploy"]["evidence"]["needs_red"], ["d1-01-stack-test"])

    def test_spec_reds_repeat_train_26(self):
        got = triage("27", previous=previous_26())
        for key, tests in ((OCR, [f"{OCR}:96"]), (WQ, [f"{WQ}:158", f"{WQ}:199"])):
            v = got[f"stack-test/desktop-e2e:{key}"]
            self.assertEqual((v["kind"], v["cause"], v["evidence"]["repeat_of"]), ("repeat", "file", "40971471569"))
            self.assertEqual(v["evidence"]["tests"], tests)
            self.assertTrue(any(key in line for line in v["evidence"]["lines"]))
        self.assertIsNone(got[f"stack-test/desktop-e2e:{OCR}"]["owner"])  # plan 0428 runs nowhere: unowned

    def test_spec_goes_to_the_field_running_its_plan(self):
        got = triage("27", previous=previous_26(), live={"05", "13"},
                     plans={"05": "0428-mac-vm-bash-test", "13": "0430-workqueue-runners-plugin"})
        self.assertEqual((got[f"stack-test/desktop-e2e:{OCR}"]["owner"], got[f"stack-test/desktop-e2e:{WQ}"]["owner"]),
                         ("05", "13"))
        self.assertTrue(got[f"stack-test/desktop-e2e:{WQ}"]["live"])
        self.assertEqual(got[f"stack-test/desktop-e2e:{WQ}"]["evidence"]["owner"]["from"]["by"], "plan")

    def test_build_timeouts_are_the_pipelines(self):
        got = triage("27", previous=previous_26())
        v = got["stack-test/hub-e2e"]
        self.assertEqual((v["kind"], v["placed"], v["owner"]), ("unsure", "pipeline", None))
        self.assertIn("no car changed", v["missing"])
        got = triage("27", previous=previous_26(), pipeline_field="27", live={"27"})
        for unit in ("stack-test/hub-e2e", "stack-test/web-e2e"):
            self.assertEqual((got[unit]["kind"], got[unit]["owner"], got[unit]["recheck"]), ("pipeline", "27", "agrees"))
            self.assertTrue(any("exit 124" in line for line in got[unit]["evidence"]["lines"]))

    def test_runner_image_repeats_with_no_owner(self):
        v = triage("27", previous=previous_26())["runner-image-linux"]
        self.assertEqual((v["kind"], v["placed"], v["cause"]), ("unsure", "repeat", "unplaced"))
        self.assertIn("40971471569", v["missing"])
        self.assertEqual(v["evidence"]["runner"], "x64_vps_hetzner_ccx33_01_linux-ubuntu_26.04_host_b")
        self.assertEqual(v["evidence"]["lines"], ["!! the user data is over 32 KiB"])

    def test_every_verdict_says_how_to_reproduce(self):
        got = triage("27", previous=previous_26())
        for v in got.values():
            self.assertEqual(v["reproduced"], run_triage.REPRODUCED)
            self.assertEqual(v["evidence"]["commit"], "addac38de02fee664143b67e882e8b7d7d44f113")
            self.assertTrue(v["key"].startswith("triage:41009203691:"))
        self.assertEqual(got["stack-test/hub-e2e"]["reproduce"],
                         f"code/bash/scripts/gate/main.sh hub-e2e --branch {TRAINS['27']['base']}")
        self.assertEqual(got["hub-deploy"]["reproduce"], "code/bash/scripts/ci-check/main.sh hub-deploy")

    def test_dedup_data_is_carried(self):
        data, jobs, log = recorded("27")
        dedup = {"orders": [{"field": "13", "why": "x"}], "wagons": ["19"], "plans": {"13": "0480-lean-tollman-tick"}}
        out = run_triage.triage({"id": "41009203691"}, jobs, log, context("27", dedup=dedup))
        self.assertEqual(out["dedup"], dedup)


class Train25(unittest.TestCase):
    """Train 25 (23 cars) after train 23's green run: no repeat; its reds placed by file and pipeline."""

    def test_reds_placed_without_a_repeat(self):
        got = triage("25", previous=[{"id": "40643116163", "units": {}}], live={"13"})
        self.assertFalse(any(v["evidence"].get("repeat_of") for v in got.values()))
        self.assertEqual(got["hub-deploy"]["kind"], "needs-red")
        wq = got[f"stack-test/desktop-e2e:{WQ}"]
        self.assertEqual((wq["kind"], wq["owner"], wq["evidence"]["owner"]["from"]["by"]), ("file", "13", "car"))
        typing = got["stack-test/desktop-e2e:e2e/electron/typing-results.spec.ts"]
        self.assertEqual((typing["kind"], typing["owner"]), ("file", None))  # plan 0337 is done: a board note
        for unit in ("stack-test/hub-e2e", "stack-test/web-e2e", "runner-image-linux"):
            self.assertEqual((got[unit]["kind"], got[unit]["placed"]), ("unsure", "pipeline"))
            self.assertIn("cars 01, 05, 09, 18, 19, 22, 23", got[unit]["missing"])


def unit(name: str, job: str, lines: list[str]) -> dict:
    return {"unit": name, "job": job, "bare": read.stack_red.bare(job), "steps": [], "lines": lines, "runner": ""}


def one(u: dict, **kw) -> dict:
    run = {"id": "1", "url": "u", "sha": "s", "base": "b"}
    ctx = context("27", red=[u["job"]], **kw)
    return run_triage.classify(run, [u], ctx)[0]


class Kinds(unittest.TestCase):
    """The kinds no recorded run shows, each a recorded unit with one line changed."""

    def setUp(self):
        _, jobs, log = recorded("27")
        self.units = {u["unit"]: u for u in read.units(jobs, log)}

    def test_runner(self):
        u = copy.deepcopy(self.units["stack-test/hub-e2e"])
        u["lines"].insert(1, "fatal: unable to access: Could not resolve host: github.com")
        v = one(u)
        self.assertEqual((v["kind"], v["owner"], v["recheck"]), ("runner", None, "agrees"))

    def test_flake(self):
        v = one(self.units["stack-test/hub-e2e"], others=[{"id": "9", "green": ["stack-test/hub-e2e"]}])
        self.assertEqual((v["kind"], v["evidence"]["green_on"], v["recheck"]), ("flake", "9", "agrees"))

    def test_car_and_unplaced(self):
        u = unit("rust-test", "c3-01-rust-test", ["##[error]code/rust/libs/x/src/lib.rs:4: assertion failed"])
        cars = [{"field": "02", "files": ["code/rust/libs/x/src/lib.rs"]}, {"field": "09", "files": ["y.md"]}]
        v = one(u, cars=cars, live={"02"})
        self.assertEqual((v["kind"], v["owner"], v["live"], v["recheck"]), ("car", "02", True, "agrees"))
        u = unit("rust-test", "c3-01-rust-test", ["##[error]something broke"])
        self.assertEqual(one(u, cars=cars)["kind"], "unplaced")

    def test_a_repeat_is_never_a_cars(self):
        u = unit("rust-test", "c3-01-rust-test", ["##[error]code/rust/libs/x/src/lib.rs:4: assertion failed"])
        cars = [{"field": "02", "files": ["code/rust/libs/x/src/lib.rs"]}]
        prev = [{"id": "7", "units": {"rust-test": {"tests": [], "timeout": False, "lines": u["lines"]}}}]
        v = one(u, cars=cars, previous=prev)
        self.assertEqual((v["kind"], v["placed"], v["cause"], v["owner"]), ("unsure", "repeat", "unplaced", None))

    def test_thin_evidence_is_unsure(self):
        v = one(unit("rust-test", "c3-01-rust-test", []))
        self.assertEqual((v["kind"], v["owner"], v["missing"]), ("unsure", None, "an error line in the job's failed log"))

    def test_unresolved_spec_is_unsure(self):
        v = one(self.units["stack-test/desktop-e2e"], paths=[])
        self.assertEqual((v["kind"], v["placed"]), ("unsure", "file"))
        self.assertIn("the spec's file in the repository", v["missing"])


class Recheck(unittest.TestCase):
    """The recheck recomputes kind and owner from the evidence alone; a disagreement gives `unsure`."""

    def setUp(self):
        self.got = triage("27", previous=previous_26(), pipeline_field="27", live={"05", "13", "27"},
                          plans={"05": "0428-mac-vm-bash-test", "13": "0430-workqueue-runners-plugin"})

    def test_agrees_on_every_replayed_verdict(self):
        for key, v in self.got.items():
            self.assertEqual(check.recheck(v["evidence"]), (v["kind"], v["owner"]), key)

    def test_a_transient_line_the_first_verdict_missed(self):
        v = copy.deepcopy(self.got[f"stack-test/desktop-e2e:{WQ}"])
        v["evidence"]["lines"].append("Error: read ECONNRESET")
        out = check.settle(v)
        self.assertEqual((out["kind"], out["owner"], out["recheck"]), ("unsure", None, "disagrees"))
        self.assertIn("recheck: runner", out["missing"])

    def test_a_spec_the_lines_do_not_name(self):
        v = copy.deepcopy(self.got[f"stack-test/desktop-e2e:{OCR}"])
        v["evidence"]["lines"] = ["##[error]gate: stack-test: desktop-e2e failed"]
        self.assertEqual(check.settle(v)["kind"], "unsure")

    def test_a_car_owner_outside_the_train(self):
        v = {"kind": "file", "owner": "44", "evidence": {"spec": "a.spec.ts", "lines": ["✘ 1 [x] › a.spec.ts:3:1"],
                                                         "cars": ["02"], "owner": {"field": "44", "from": {"by": "car"}}}}
        self.assertEqual(check.recheck(v["evidence"]), ("file", "?"))
        self.assertEqual(check.settle(v)["kind"], "unsure")

    def test_pipeline_without_one_field(self):
        e = {"lines": ["phase build: failed after 600s (exit 124)"], "pipeline": {"cars": ["01", "05"]}}
        self.assertEqual(check.recheck(e), ("unsure", None))


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def commit(repo: str, path: str, message: str) -> None:
    f = Path(repo, path)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(message)
    git(repo, "add", path)
    git(repo, "commit", "-q", "-m", message)


class Gather(unittest.TestCase):
    """The reading half against a real git repository and a fake gh (gh_fake): train 27's recorded run and train 26's
    before it; one `--log-failed` per red run, nothing else run."""

    @classmethod
    def setUpClass(cls):
        cls.main = tempfile.mkdtemp()
        main = cls.main
        git(main, "init", "-q", "-b", "main")
        git(main, "config", "user.email", "t@t")
        git(main, "config", "user.name", "t")
        commit(main, ".github/workflows/merge-to-main-cloud.yml", (FIX / "workflow.yml").read_text())
        for job in ("hub-e2e", "web-e2e", "desktop-e2e"):
            commit(main, f"code/bash/scripts/gate/jobs/{job}.sh", job)
        desk = "code/typescript/apps/hal9k-desktop/e2e/electron/"
        commit(main, desk + "ocr.spec.ts", "fix(0428|8): ocr\n\nPlan: 0428-mac-vm-bash-test")
        commit(main, desk + "workqueue.spec.ts", "feat(0430|7): wq\n\nWorktree: 13\nPlan: 0430-workqueue")
        base = git(main, "rev-parse", "HEAD")
        git(main, "checkout", "-q", "-b", "02")
        commit(main, "code/python/x.py", "x")
        cls.train = {"base": base, "cars": [{"field": "02", "head": git(main, "rev-parse", "HEAD")}]}
        git(main, "checkout", "-q", "main")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.main, True)

    def setUp(self):
        from gh_fake import FakeGh, run
        jobs = {n: recorded(n)[1] for n in ("27", "26")}
        logs = {n: recorded(n)[2] for n in ("27", "26")}
        base = self.train["base"]
        self.gh = FakeGh(runs=[run(41009203691, "land/train-27-3", "2026-10-30T05:34:43Z", sha=base),
                               run(40990220924, "land/train-27-2", "2026-10-30T02:11:23Z", conclusion="cancelled"),
                               run(40971471569, "land/train-26-1", "2026-10-29T23:12:05Z", sha="f" * 40)],
                         jobs={"41009203691": jobs["27"], "40971471569": jobs["26"]},
                         logs={"41009203691": logs["27"], "40971471569": logs["26"]}).start(self)

    def test_gathers_and_triages(self):
        url = "https://github.com/x/actions/runs/41009203691"
        run, jobs, log, ctx = gather.gather(self.main, self.train, url, {"13": "%1"}, dedup={"wagons": ["19"]})
        self.assertEqual((run["id"], run["base"]), ("41009203691", self.train["base"]))
        self.assertEqual(ctx["graph"]["e4"], ["a1", "b1", "d1", "d2"])
        self.assertEqual([p["id"] for p in ctx["previous"]], ["40971471569"])
        self.assertEqual(ctx["cars"], [{"field": "02", "files": ["code/python/x.py"]}])
        self.assertEqual(ctx["dedup"]["wagons"], ["19"])
        got = {v["key"].split(":", 2)[2]: v for v in run_triage.triage(run, jobs, log, ctx)["verdicts"]}
        wq = got[f"stack-test/desktop-e2e:{WQ}"]
        self.assertEqual((wq["kind"], wq["owner"], wq["live"]), ("repeat", "13", True))
        self.assertEqual(wq["evidence"]["owner"]["from"]["by"], "worktree")
        self.assertEqual(got["hub-deploy"]["kind"], "needs-red")
        failed = [c for c in self.gh.calls if c[-1] == "--log-failed"]
        self.assertEqual(sorted(c[3] for c in failed), ["40971471569", "41009203691"])
        self.assertFalse([c for c in self.gh.calls if "gate" in " ".join(c)])

    def test_the_previous_signatures_handed_in(self):
        url = "https://github.com/x/actions/runs/41009203691"
        gather.gather(self.main, self.train, url, {}, earlier=[])
        self.assertEqual([c[3] for c in self.gh.calls if c[-1] == "--log-failed"], ["41009203691"])


if __name__ == "__main__":
    unittest.main()
