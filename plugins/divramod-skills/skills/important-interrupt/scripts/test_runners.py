"""runners.py's host runners source: the folders give the repos, `runner stop --all` per repo (no --force), a busy
runner left to retry, the undo `runner start` only for the runners this stop stopped; the machine and hal2-cli-ci
are fakes (CiSys), the folders and the stop record live in a temp root; no real runner is stopped or started."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

import interrupt  # first: it puts stop-all-agent-work's scripts on sys.path
import resume
import runners
import stopall
from test_freeze import FakeSys

FOLDERS = ("divramod-hal2-a", "divramod-hal2-b", "divramod-my-notebook-lm-a", "divramod-my-notebook-lm-b",
           "divramod-jobsearch-a")


def runner(repo, letter, **kw):
    name = repo.split("/")[1]
    return {"name": f"mac-host-{name}-{letter}", "repo": repo, "letter": letter, "registered": True,
            "online": True, "busy": False, "agent": "running", "listed": True, "enabled": True, "stopped": False,
            "current_job": None, **kw}


def pool():
    return [runner("divramod/hal2", "a"), runner("divramod/hal2", "b"), runner("divramod/my-notebook-lm", "a"),
            runner("divramod/my-notebook-lm", "b", stopped=True, agent="stopped", online=False),
            runner("divramod/jobsearch", "a")]


class CiSys(FakeSys):
    """FakeSys plus hal2-cli-ci: `runner status` answers the runners, `runner stop|start` is logged and flips
    `stopped`; `busy_letters` refuse a stop with exit 5 (`--all` too), `fail_all` fails `--all` with exit 1."""

    def __init__(self, cli, runners_=None, status_code=0, stop_code=0, busy_letters=(), fail_all=False):
        super().__init__({})
        self.cli, self.runners = cli, runners_ if runners_ is not None else pool()
        self.status_code, self.stop_code = status_code, stop_code
        self.busy_letters, self.fail_all = set(busy_letters), fail_all
        self.ci = []

    def run(self, cmd, timeout=60):
        if cmd[0] != self.cli:
            return super().run(cmd, timeout)
        cmd = [c for c in cmd if c != "--json"]
        self.ci.append((cmd[1:], timeout))
        verb, args = cmd[1:3], cmd[3:]
        if verb == ["runner", "status"]:
            if self.status_code:
                return self.status_code, "", "timed out after 45s" if self.status_code == 124 else "no network"
            return 0, json.dumps({"runners": self.runners}), ""
        repo, letter = args[args.index("--repo") + 1], args[args.index("--letter") + 1] if "--letter" in args else None
        mine = [r for r in self.runners if r["repo"] == repo and (letter is None or r["letter"] == letter)]
        if verb == ["runner", "stop"]:
            if self.stop_code:
                return self.stop_code, "", "boom"
            if any(r["letter"] in self.busy_letters for r in mine):
                return runners.BUSY, "", "runner runs a job"
            if letter is None and self.fail_all:
                return 1, "", "half done"
            for r in mine:
                r["stopped"] = True
            return 0, json.dumps({"repo": repo, "runners": mine}), ""
        for r in mine:
            r["stopped"] = False
        return 0, "{}", ""

    def stops(self):
        return [" ".join(c) for c, _ in self.ci if c[:2] == ["runner", "stop"]]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        for f in FOLDERS:
            (base / "runners" / f).mkdir(parents=True)
        (base / "runners" / "divramod-notes.txt").write_text("x")  # a file, not a runner
        (base / "runners" / "other-repo-a").mkdir()  # not divramod's
        self.cli = base / "hal2-cli-ci"
        self.cli.write_text("#!/bin/sh\nexit 99\n")  # never run: CiSys answers it
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        self.env = {"STOP_ALL_AGENT_WORK_ROOT": str(base / "stop"), "IMPORTANT_INTERRUPT_ROOT": str(base / "ii"),
                    "HAL2_CLI_CI": str(self.cli), "HAL2_HOST_RUNNER_ROOT": str(base / "runners")}
        self.saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.lines = []
        self.use(CiSys(str(self.cli)))

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.tmp.cleanup()

    def use(self, sys_):
        self.sys = sys_
        self.d = interrupt.Deps(sys_, None, None, stopall, out=self.lines.append, getpid=lambda: 502)

    def actions(self):
        return json.loads(stopall.record().read_text())["actions"] if stopall.record().exists() else []

    def out(self):
        return "\n".join(self.lines)


class DiscoverTest(Base):
    def test_repos_from_the_folders_the_letter_is_the_last_segment(self):
        self.assertEqual(runners.discover(), {"divramod/hal2": ["a", "b"], "divramod/jobsearch": ["a"],
                                              "divramod/my-notebook-lm": ["a", "b"]})

    def test_a_missing_root_finds_nothing(self):
        self.assertEqual(runners.discover(Path(self.tmp.name) / "nope"), {})


class StopTest(Base):
    def test_one_stop_all_per_repo_without_force_and_a_row_per_runner(self):
        res = runners.host_runners(self.d, False)
        self.assertEqual(res["source"], "host runners")
        self.assertEqual(self.sys.stops(), ["runner stop --repo divramod/hal2 --all",
                                            "runner stop --repo divramod/jobsearch --all",
                                            "runner stop --repo divramod/my-notebook-lm --all"])
        self.assertFalse(any("--force" in c for c, _ in self.sys.ci))
        self.assertTrue(all(t <= max(runners.PROBE, runners.CALL) for _, t in self.sys.ci))
        self.assertEqual(res["kinds"], [runners.KIND] * 4)
        names = [a["text"] for a in self.actions()]
        self.assertEqual(names, ["stop host runner mac-host-hal2-a", "stop host runner mac-host-hal2-b",
                                 "stop host runner mac-host-jobsearch-a", "stop host runner mac-host-my-notebook-lm-a"])
        self.assertEqual(self.actions()[0]["undo"], [str(self.cli), "runner", "start", "--repo", "divramod/hal2",
                                                     "--letter", "a"])
        self.assertEqual((res["note"]["repos"], res["note"]["already"], res["note"]["busy"]), (3, 1, []))

    def test_done_starts_only_the_runners_this_stop_stopped(self):
        runners.host_runners(self.d, False)
        self.sys.ci.clear()
        kinds = resume.undo_machine(self.d, self.actions(), False)
        self.assertEqual(kinds, [runners.KIND] * 4)
        starts = [" ".join(c) for c, _ in self.sys.ci]
        self.assertEqual(len(starts), 4)
        self.assertNotIn("my-notebook-lm --letter b", " ".join(starts))  # stopped before: stays stopped (D8)
        self.assertEqual(starts[0], "runner start --repo divramod/my-notebook-lm --letter a")  # newest first
        self.assertEqual(starts[-1], "runner start --repo divramod/hal2 --letter a")
        self.assertTrue(all(not r["stopped"] for r in self.sys.runners if r["letter"] == "a"))
        self.assertTrue(next(r for r in self.sys.runners if r["letter"] == "b" and "notebook" in r["name"])["stopped"])

    def test_a_busy_runner_is_refused_reported_and_the_idle_ones_still_stop(self):
        rs = pool()
        rs[1]["busy"] = True
        self.use(CiSys(str(self.cli), rs))
        res = runners.host_runners(self.d, False)
        self.assertEqual(res["note"]["busy"], ["mac-host-hal2-b"])
        self.assertIn("mac-host-hal2-b runs a job: not stopped (no --force)", self.out())
        self.assertIn("runner stop --repo divramod/hal2 --letter a", self.sys.stops())
        self.assertNotIn("runner stop --repo divramod/hal2 --all", self.sys.stops())
        self.assertEqual([a["text"] for a in self.actions()].count("stop host runner mac-host-hal2-b"), 0)
        self.assertTrue(rs[1]["agent"] == "running" and not rs[1]["stopped"])

    def test_retry_stops_the_runner_once_its_job_is_done(self):
        rs = pool()
        rs[1]["busy"] = True
        self.use(CiSys(str(self.cli), rs))
        runners.host_runners(self.d, False)
        self.assertEqual(runners.retry(self.d)[1], ["mac-host-hal2-b"])  # still busy
        rs[1]["busy"] = False
        self.assertEqual(runners.retry(self.d), ([runners.KIND], []))
        self.assertEqual(self.sys.stops()[-1], "runner stop --repo divramod/hal2 --all")
        self.assertEqual([a["text"] for a in self.actions()].count("stop host runner mac-host-hal2-b"), 1)

    def test_a_job_started_after_the_status_probe_is_refused_by_the_cli_and_reported(self):
        self.use(CiSys(str(self.cli), busy_letters=("a",)))  # the status said idle, the CLI refuses (exit 5)
        res = runners.host_runners(self.d, False)
        self.assertEqual(sorted(res["note"]["busy"]), ["mac-host-hal2-a", "mac-host-jobsearch-a",
                                                       "mac-host-my-notebook-lm-a"])
        self.assertEqual([a["text"] for a in self.actions()], ["stop host runner mac-host-hal2-b"])

    def test_a_failed_stop_all_falls_back_to_the_letters(self):
        self.use(CiSys(str(self.cli), fail_all=True))
        res = runners.host_runners(self.d, False)
        self.assertIn("runner stop --all divramod/hal2 failed (exit 1: half done): per runner", self.out())
        self.assertEqual(len(res["kinds"]), 4)
        self.assertIn("runner stop --repo divramod/hal2 --letter b", self.sys.stops())

    def test_a_failing_stop_is_reported_not_fatal_and_recorded_nowhere(self):
        self.use(CiSys(str(self.cli), stop_code=124))
        res = runners.host_runners(self.d, False)
        self.assertIn("runner stop --all divramod/hal2 failed (exit 124", self.out())
        self.assertEqual((res["kinds"], self.actions()), ([], []))


class MissingTest(Base):
    def test_missing_cli_is_reported_not_fatal(self):
        os.environ["HAL2_CLI_CI"] = str(Path(self.tmp.name) / "nope")
        res = runners.host_runners(self.d, False)
        self.assertIn("hal2-cli-ci not found", self.out())
        self.assertEqual((res["kinds"], res["note"], self.sys.ci), ([], {"cli": None}, []))
        self.assertEqual(runners.retry(self.d), ([], []))

    def test_no_folders_no_stop(self):
        os.environ["HAL2_HOST_RUNNER_ROOT"] = str(Path(self.tmp.name) / "nope")
        res = runners.host_runners(self.d, False)
        self.assertIn("no host runner folders", self.out())
        self.assertEqual((res["kinds"], self.sys.ci), ([], []))

    def test_unreadable_status_stops_by_the_folders_with_a_warning(self):
        for code in (124, 1):
            self.use(CiSys(str(self.cli), status_code=code))
            self.lines.clear()
            stopall.finish() if stopall.record().exists() else None
            res = runners.host_runners(self.d, False)
            self.assertIn("host runner status not readable", self.out())
            self.assertIn("done starts every runner of those folders", self.out())
            self.assertEqual(res["note"]["status"], "unreadable")
            self.assertEqual(len(res["kinds"]), 5)
            self.assertEqual(self.sys.ci[0][1], runners.PROBE)


class DryRunTest(Base):
    def test_dry_run_probes_only_and_lists_every_stop_and_undo(self):
        res = runners.host_runners(self.d, True)
        self.assertEqual([c[:2] for c, _ in self.sys.ci], [["runner", "status"]])
        self.assertFalse(stopall.record().exists())
        self.assertEqual(res["kinds"], [runners.KIND] * 4)
        self.assertIn("would stop host runner mac-host-hal2-a", self.out())
        self.assertIn("runner start --repo divramod/hal2 --letter a", self.out())
        self.assertNotIn("mac-host-my-notebook-lm-b", self.out())  # stopped already

    def test_dry_run_names_a_busy_runner_as_refused(self):
        rs = pool()
        rs[0]["current_job"] = {"repo": "divramod/hal2", "run": "1", "job": "x", "started": "t"}
        self.use(CiSys(str(self.cli), rs))
        res = runners.host_runners(self.d, True)
        self.assertIn("busy: would be refused", self.out())
        self.assertEqual(res["note"]["busy"], ["mac-host-hal2-a"])

    def test_sources_lists_the_source(self):
        self.assertEqual([n for n, _ in runners.SOURCES], ["host runners"])


if __name__ == "__main__":
    unittest.main()
