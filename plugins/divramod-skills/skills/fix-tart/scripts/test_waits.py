"""fix-tart's VM job waits and the cases of plan 0391 step 11, from fixtures: no network."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import signatures  # noqa: E402
import waits  # noqa: E402

UTC = timezone.utc
VM = ["self-hosted", "macOS", "ARM64", "hal2", "mac-vm-a"]


def job(name, created, started, ended, labels=VM, runner="arm64_loc_macbookpro_18.4_01_macos_26_vm_a"):
    return {"name": name, "labels": labels, "created_at": created, "started_at": started,
            "completed_at": ended, "runner_name": runner, "conclusion": "success"}


# Land run 39202611602 (2026-10-19): c4-02 shares its lane's created_at and waited 68 s for a fresh clone after
# c4-01 ended; f4 waited for one after e3.
RUN = [
    job("c4-01-bash-test", "2026-10-19T05:06:54Z", "2026-10-19T05:06:56Z", "2026-10-19T05:07:02Z"),
    job("c4-02-tmux-test-mac", "2026-10-19T05:06:54Z", "2026-10-19T05:08:10Z", "2026-10-19T05:08:24Z"),
    job("e3-01-tmux-publish-mac", "2026-10-19T05:25:53Z", "2026-10-19T05:25:55Z", "2026-10-19T05:26:18Z"),
    job("f4-01-ci-cache-clean-mac-vm", "2026-10-19T05:26:19Z", "2026-10-19T05:32:25Z", "2026-10-19T05:33:02Z"),
    job("a1-01-ci-route", "2026-10-19T05:04:00Z", "2026-10-19T05:04:01Z", "2026-10-19T05:04:30Z",
        labels=["self-hosted", "macOS", "ARM64", "mac-host-a"]),
    dict(job("e3-${{ matrix.pos }}-${{ matrix.job }}", "2026-10-19T05:25:53Z", None, None), conclusion="skipped"),
]


class Waits(unittest.TestCase):
    def test_a_lanes_next_job_waits_from_the_end_of_the_one_before(self):
        rows = waits.gaps(39202611602, RUN)
        self.assertEqual([(name[:5], wait) for _, name, wait, _ in rows],
                         [("c4-01", 2), ("c4-02", 68), ("e3-01", 2), ("f4-01", 366)])
        lines, all_under = waits.report([(39202611602, RUN)])
        self.assertFalse(all_under)
        self.assertEqual(lines[-1], "4 VM jobs: median 35s, p90 68s, max 366s, 2 under 15s")

    def test_waits_under_the_bound_pass_the_check(self):
        fast = [job("c4-01-bash-test", "2026-10-19T05:06:54Z", "2026-10-19T05:06:56Z", "2026-10-19T05:07:02Z"),
                job("c4-02-tmux-test-mac", "2026-10-19T05:06:54Z", "2026-10-19T05:07:10Z", "2026-10-19T05:07:20Z")]
        self.assertTrue(waits.report([(1, fast)])[1])
        self.assertEqual(waits.summary([]), "no VM job ran")

    def test_the_last_runs_are_asked_of_gh(self):
        answers = {"workflows/merge-to-main.yml/runs?per_page=2": '{"workflow_runs":[{"id":5},{"id":6}]}',
                   "runs/5/jobs": '{"jobs":[]}', "runs/6/jobs": '{"jobs":[]}'}

        def run(cmd):
            return next((v for k, v in answers.items() if k in cmd[2]), None)
        self.assertEqual(waits.land_runs(run, "o/r", 2), [(5, []), (6, [])])
        self.assertIsNone(waits.land_runs(lambda cmd: None, "o/r", 2))


def task(name, lines, start="06:00", end="06:01"):
    day = "2026-10-19T"
    return {"name": name, "start": datetime.fromisoformat(day + start + ":00+00:00"),
            "end": datetime.fromisoformat(day + end + ":00+00:00"), "lines": lines}


class Cases(unittest.TestCase):
    def test_a_boot_that_waited_its_whole_bound_for_secrets_is_case_8(self):
        waited = task("01a152a2", ["clone: 3.9s", "the secrets did not resolve within 60s (hal2-secrets' listing "
                                    "and gpg are slow on a busy Mac, or gpg waits for its passphrase)", "boot: 60.0s"])
        kept = task("01a152a5", ["env: kept from 812s ago", "booted in 26s", "Running job: c4-01-bash-test"])
        ctx = {"tasks": [waited, kept], "daemon": []}
        found = signatures.secrets_wait(ctx)
        self.assertEqual([f["slug"] for f in found], ["secrets-wait"])
        self.assertIn("1 runner tasks", found[0]["detail"])

    def test_a_vm_that_booted_and_ran_no_job_is_case_9(self):
        # The 23:18:10 restart cancelled mveg3eok in its secrets wait; mveg4vsi ran c4-01.
        restarted = task("01a1519b", ["$ tart clone hal2-ci-runner-macos-e8de00e7 hal2-hal2-ci-runner-macos_mveg3eok",
                                      "boot: 75.2s", "$ tart delete hal2-hal2-ci-runner-macos_mveg3eok"])
        parked = task("01a1519d", ["$ tart clone hal2-ci-runner-macos-e8de00e7 hal2-hal2-ci-runner-macos_mveh0000",
                                   "booted in 30s", "boot: 31.0s", "2026-10-18 23:40:00Z: Listening for Jobs",
                                   "command: 600.0s"])
        ran = task("01a1519c", ["$ tart clone hal2-ci-runner-macos-e8de00e7 hal2-hal2-ci-runner-macos_mveg4vsi",
                                "booted in 42s", "2026-10-18 23:20:14Z: Running job: c4-01-bash-test", "command: 22.9s"])
        found = signatures.jobless({"tasks": [restarted, parked, ran], "daemon": []})
        self.assertEqual([f["slug"] for f in found], ["jobless"])
        self.assertIn("2 VMs booted and ran no job (01a1519b, 01a1519d)", found[0]["detail"])
        self.assertEqual(signatures.jobless({"tasks": [ran], "daemon": []}), [])


if __name__ == "__main__":
    unittest.main()
