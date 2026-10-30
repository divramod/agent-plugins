"""Hal2 plan 0383 step 11 (D12, D13): the tollman owns CI/CD health. Every pass of the 1-minute watch checks all
runners of hal2-runners.toml; a healthy fleet prints nothing, each problem is one line, once. The regression replays
run 39162581704 (2026-10-18): b1-01-ci-changes queued 20:17:09 UTC with hz01 parked. Whole ticks on test_minute's
farm; gh is gh_fake.py's, the supervisor's journal and the state root are the test's own, no machine is touched."""
# enforces .adr/park-the-linux-runner-asap.md and .adr/deterministic-first.md

import datetime as dt
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import ci_fleet
import ci_health
from gh_fake import api_job, runner
from skillpath import repo_root
from test_minute import Pass

TOML = repo_root(__file__) / ci_fleet.TOML
LOG = """2026-10-18T18:40:25Z hz01: hetzner says up; no queued or running job of any run for its runners
2026-10-18T19:07:03Z hz01: hetzner says parked; no queued or running job of any run for its runners
2026-10-18T20:08:13Z hz01: hetzner says parked; no queued or running job of any run for its runners
2026-10-18T20:08:24Z az01: azure says parked; no queued or running job of any run for its runners
"""
WOKEN = """2026-10-18T20:19:51Z hz01: wake (hetzner says parked; 1 jobs: run 501 job 7): ok
"""
HZ = ["self-hosted", "linux", "x64", "hz01-host-a"]
MAC = ["self-hosted", "macOS", "ARM64", "mac-host-hal2-a"]
VM = ["self-hosted", "macOS", "ARM64", "hal2", "mac-vm-a"]
CI_CHANGES = api_job(117778863640, "b1-01-ci-changes", HZ, "2026-10-18T20:17:09Z")


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class Health(Pass):
    def setUp(self):
        super().setUp()
        (self.main / ".github").mkdir(exist_ok=True)
        shutil.copy(TOML, self.main / ci_fleet.TOML)
        self.state = self.tmp / "state"
        (self.state / "ci-supervisor").mkdir(parents=True)
        self.log = self.state / "ci-supervisor/power.log"
        self.log.write_text(LOG)
        p = mock.patch.dict(os.environ, {"HAL2_STATE_DIR": str(self.state)})
        p.start()
        self.addCleanup(p.stop)
        self.now = dt.datetime.now(dt.timezone.utc)
        self.fleet(online=True)

    def fleet(self, online=True, **status):
        """Every runner of the toml listed (GitHub lists a parked server online: the stale listing of 2026-10-18)."""
        self.gh.runners = [runner(r["name"], status.get(r["code"], "online" if online else "offline"), r["labels"])
                           for r in ci_fleet.catalog(str(self.main))]

    def queue(self, *jobs):
        self.gh.api_jobs["501"] = list(jobs)

    def requests(self):
        return sorted((self.state / "ci-supervisor/wake-requests").glob("*.json"))

    def check(self, minutes=0, dry=False):
        return ci_health.check(str(self.wm), str(self.main), self.now + dt.timedelta(minutes=minutes), dry)


class Replay(Health):
    def test_run_39162581704_a_queued_job_with_hz01_parked_is_one_line_and_a_wake_request_at_once(self):
        self.queue(CI_CHANGES)
        out = self.tick()
        self.assertEqual(out.count("\n"), 1, out)
        self.assertIn("runners: job b1-01-ci-changes (run 501, queued 20:17Z) waits for [hz01-host-a,linux,x64]: "
                      "hz01 is parked; asked the CI supervisor to wake it", out)
        (req,) = self.requests()
        doc = json.loads(req.read_text())
        self.assertEqual((req.name, doc["machine"], doc["by"], doc["job"], doc["job_name"], doc["labels"], doc["schema"]),
                         ("hz01.json", "hz01", "tollman", "117778863640", "b1-01-ci-changes", sorted(HZ), 1))
        self.assertIn(str(req), out)
        self.assertEqual(self.tick(), "", "the next minute: told once")
        self.assertEqual(json.loads(req.read_text()), doc, "the standing request is kept as it is")
        self.assertTrue([e["key"] for e in self.wm_log() if e["kind"] == "runner"][0].startswith("ci-health:wake:117778863640:"))

    def test_the_wake_ordered_the_problem_is_gone_and_the_request_withdrawn(self):
        self.queue(CI_CHANGES)
        self.tick()
        self.log.write_text(LOG + WOKEN)
        self.assertEqual(self.tick(), "", "waking: the supervisor is on it")
        self.assertEqual(self.requests(), [])
        self.log.write_text(LOG + WOKEN + "2026-10-18T20:20:26Z hz01: hetzner says up; 1 jobs: run 501 job 7\n")
        self.assertEqual(self.tick(), "", "up, and GitHub lists the runner online: served")

    def test_a_dry_look_writes_no_request_and_keeps_nothing(self):
        self.queue(CI_CHANGES)
        (action,) = self.check(dry=True)
        self.assertIn("hz01 is parked", action["text"])
        self.assertEqual((self.requests(), (self.wm_state / ci_health.FILE).exists()), ([], False))
        self.assertEqual(len(self.check()), 1, "the dry look told nothing")


class Healthy(Health):
    def test_a_healthy_fleet_prints_nothing_and_asks_for_nothing(self):
        self.log.write_text(LOG.replace("hz01: hetzner says parked", "hz01: hetzner says up"))
        self.queue(api_job(1, "a1-01-ci-route", MAC, stamp(self.now)), api_job(2, "b1-01-ci-changes", HZ, stamp(self.now)))
        self.assertEqual(self.tick(), "")
        self.assertEqual(self.requests(), [])

    def test_a_parked_machine_nobody_needs_is_no_problem(self):
        self.queue(api_job(1, "a1-01-ci-route", MAC, stamp(self.now)))
        self.assertEqual(self.tick(), "", "hz01 and az01 are parked, no queued job wants them")

    def test_a_busy_runner_is_a_queue_not_a_problem_and_github_hosted_jobs_are_not_ours(self):
        self.fleet(**{"mac-host-hal2-a": "online"})
        self.gh.runners[[r["name"] for r in self.gh.runners].index(
            next(r["name"] for r in ci_fleet.catalog(str(self.main)) if r["code"] == "mac-host-hal2-a"))]["busy"] = True
        self.queue(api_job(1, "a1-01-ci-route", MAC, stamp(self.now - dt.timedelta(minutes=30))),
                   api_job(2, "x", ["ubuntu-latest"], stamp(self.now - dt.timedelta(minutes=30))))
        self.assertEqual(self.tick(), "")

    def test_github_not_answering_judges_nothing(self):
        self.gh.runners = None
        self.queue(CI_CHANGES)
        self.assertEqual((self.tick(), self.requests()), ("", []))


class LazyRunners(Health):
    """Plan 0480 D2: GitHub's runners are asked once a pass, only when a check needs them."""

    def only_hz01(self):
        """A toml of hz01's three runners alone (the journal: parked), no pipeline host runner awake."""
        doc = (TOML.read_text().split("[[runners]]")[0] + "".join(
            "[[runners]]" + part for part in TOML.read_text().split("[[runners]]")[1:] if 'code = "hz01-' in part))
        (self.main / ci_fleet.TOML).write_text(doc)
        self.assertEqual({r["machine"] for r in ci_fleet.catalog(str(self.main))}, {"hz01"})

    def test_a_pass_with_no_check_needing_them_never_asks_for_the_runners(self):
        self.only_hz01()
        self.gh.runners = None  # GitHub would not answer: never asked, so nothing is blinded
        self.queue(api_job(2, "x", ["ubuntu-latest"], stamp(self.now - dt.timedelta(minutes=30))))
        self.assertEqual((ci_health.problems(str(self.main), self.now), self.gh.runner_lists()), ([], 0))
        self.queue(CI_CHANGES)  # its only candidates are parked: the wake needs no runners list
        (p,) = ci_health.problems(str(self.main), self.now)
        self.assertEqual((p["kind"], self.gh.runner_lists()), ("wake", 0))
        self.log.write_text(LOG + WOKEN)  # waking: nothing to judge, still no list
        self.assertEqual((ci_health.problems(str(self.main), self.now), self.gh.runner_lists()), ([], 0))

    def test_a_check_that_needs_them_asks_once_a_pass(self):
        self.only_hz01()
        self.log.write_text(LOG.replace("hz01: hetzner says parked", "hz01: hetzner says up"))
        self.queue(CI_CHANGES, api_job(2, "b1-02-x", HZ, stamp(self.now)))  # hz01 awake: is its runner online?
        self.assertEqual((ci_health.problems(str(self.main), self.now), self.gh.runner_lists()), ([], 1))
        self.gh.runners = None
        self.assertIsNone(ci_health.problems(str(self.main), self.now), "asked and unanswered: nothing is judged")
        self.assertEqual(self.gh.runner_lists(), 2)

    def test_the_host_offline_check_asks_for_them_without_a_queued_job(self):
        self.assertEqual((self.check(), self.gh.runner_lists()), ([], 1), "the Mac's pipeline host runners are awake")


class Problems(Health):
    def test_a_mac_vm_job_waiting_past_the_grace_runs_the_doctor_once(self):
        self.fleet(**{"mac-vm-a": "offline"})  # the VM runner is on GitHub only while a VM runs
        job = api_job(9, "a2-01-mac-build", VM, stamp(self.now - dt.timedelta(minutes=2)))
        self.queue(job)
        with mock.patch.object(ci_health, "doctor", return_value="watchdog-restart (2)") as doctor:
            self.assertEqual(self.check(), [], "queued 2 min: the supervisor's wake grace is 5")
            self.queue(dict(job, created_at=stamp(self.now - dt.timedelta(minutes=6))))
            (a,) = self.check()
            self.assertEqual(self.check(), [])
        self.assertEqual(doctor.call_count, 1, "the doctor runs for the new problem only")
        self.assertEqual(a["text"], "runners: job a2-01-mac-build (run 501, queued "
                         f"{(self.now - dt.timedelta(minutes=6)).strftime('%H:%M')}Z) waits 6 min for the Mac VM "
                         "runner, none online; fix-tart doctor: watchdog-restart (2)")
        self.assertEqual((a["duty"], a["kind"], a["do"]), ("ci-health", "runner", "wake"))
        self.assertEqual(a["evidence"]["job"]["labels"], sorted(x.lower() for x in VM))

    def test_a_job_whose_host_runner_is_offline_is_reported_after_the_restart_grace(self):
        self.fleet(**{"mac-host-hal2-a": "offline"})
        self.queue(api_job(3, "a1-01-ci-route", MAC, stamp(self.now - dt.timedelta(minutes=1))))
        self.assertEqual(self.check(), [])
        self.queue(api_job(3, "a1-01-ci-route", MAC, stamp(self.now - dt.timedelta(minutes=4))))
        (a,) = self.check()
        self.assertIn("waits 4 min for [arm64,mac-host-hal2-a,macos]: mac-host-hal2-a offline", a["text"])
        self.assertEqual(self.check(), [])

    def test_a_job_no_runner_of_the_toml_can_take_is_unserved(self):
        self.queue(api_job(4, "z-typo", ["self-hosted", "no-such-label"], stamp(self.now - dt.timedelta(minutes=4))))
        (a,) = self.check()
        self.assertIn("no runner of hal2-runners.toml has these labels", a["text"])

    def test_an_idle_pipeline_host_runner_offline_is_reported_once_after_the_grace(self):
        self.fleet(**{"mac-host-hal2-b": "offline"})
        self.assertEqual(self.check(0), [], "first seen: GitHub flaps")
        self.assertEqual(self.check(2), [])
        (a,) = self.check(4)
        self.assertEqual(a["text"], "runners: host runner mac-host-hal2-b is offline for 4 min (the supervisor restarts it)")
        self.assertEqual(self.check(5), [], "once while it lasts")
        self.fleet()
        self.assertEqual(self.check(6), [], "back online: cleared")
        self.fleet(**{"mac-host-hal2-b": "offline"})
        self.assertEqual((self.check(7), len(self.check(11))), ([], 1), "offline again: a new problem, after the grace")

    def test_hand_started_and_parked_runners_are_no_problem_while_idle(self):
        self.fleet(online=False)  # everything offline: the parked servers, the VM and Docker runners, the old laptops
        found = {a["text"].split()[3] for a in self.check(0) + self.check(5)}
        self.assertEqual(found, {"mac-host-hal2-a", "mac-host-hal2-b", "mac-host-hal2-c"}, "only the Mac's pipeline host runners")


class Reading(unittest.TestCase):
    def test_the_journal_gives_each_machine_its_last_state_and_a_wake_under_way(self):
        got = ci_fleet.machines(LOG + WOKEN)
        self.assertEqual((got["hz01"]["state"], got["hz01"]["waking"], got["az01"]["waking"]), ("parked", True, False))
        self.assertEqual(ci_fleet.machines(LOG + WOKEN + "2026-10-18T20:20:26Z hz01: hetzner says up; x\n")["hz01"],
                         {"state": "up", "at": "2026-10-18T20:20:26Z", "waking": False})
        self.assertEqual(ci_fleet.power(Path("/nonexistent/power.log")), {})

    def test_the_state_root_follows_hal2_core(self):
        self.assertEqual(ci_fleet.state_root({"HAL2_STATE_DIR": "/s", "XDG_STATE_HOME": "/x"}), Path("/s"))
        self.assertEqual(ci_fleet.state_root({"XDG_STATE_HOME": "/x", "HOME": "/h"}), Path("/x/hal2"))
        self.assertEqual(ci_fleet.state_root({"HOME": "/h"}), Path("/h/.local/state/hal2"))

    def test_the_doctor_s_findings_become_one_phrase(self):
        out = json.dumps({"hours": 2, "findings": [{"slug": "slept"}, {"slug": "slept"}, {"slug": "gh-auth"}]})
        with mock.patch.object(ci_health.tick, "sh", return_value=(0, out)):
            self.assertEqual(ci_health.doctor("/x"), "slept (2), gh-auth (1)")
        with mock.patch.object(ci_health.tick, "sh", return_value=(0, json.dumps({"hours": 2, "findings": []}))):
            self.assertEqual(ci_health.doctor("/x"), "no case")
        with mock.patch.object(ci_health.tick, "sh", return_value=(2, "hal2-daemon is missing")):
            self.assertEqual(ci_health.doctor("/x"), "it failed (exit 2)")


if __name__ == "__main__":
    unittest.main()
