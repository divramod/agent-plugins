"""fix-tart's evidence: the sources read from fixtures, the known cases replayed, the CLI end to end.
No network, no hal2-daemon, no tart: every source is a file here."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import evidence  # noqa: E402
import signatures  # noqa: E402
import sources  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 10, 16, 6, 10, tzinfo=UTC)

# The 2026-10-16 incident, land run 38856671199 (cases 1 and 2): the task logs as hal2-vm wrote them.
TASK_401 = """registering arm64_loc_macbookpro_18.4_01_macos_26_vm_a on divramod/hal2
/opt/homebrew/bin/gh exited with code 1: gh: Requires authentication (HTTP 401)"""
TASK_DEAD_BOOT = """registering arm64_loc_macbookpro_18.4_01_macos_26_vm_a on divramod/hal2
slot: 0.2s
slot 1
$ tart clone ghcr.io/cirruslabs/macos-tahoe-xcode:27 hal2-hal2-ci-runner-macos_mvak1j4z
clone: 1.5s
copy in: 0.0s
$ tart run --no-graphics hal2-hal2-ci-runner-macos_mvak1j4z
boot: 402.4s
$ tart delete hal2-hal2-ci-runner-macos_mvak1j4z
delete: 0.0s
removing arm64_loc_macbookpro_18.4_01_macos_26_vm_a from divramod/hal2"""
TASK_HUNG = "\n".join(TASK_DEAD_BOOT.splitlines()[:6])  # still at `copy in: 0.0s`
TASK_GOOD = """registering arm64_loc_macbookpro_18.4_01_macos_26_vm_a on divramod/hal2
copy in: 0.0s
$ tart run --no-graphics hal2-hal2-ci-runner-macos_mvakv8n1
booted in 20s
boot: 25.0s
command: 89.0s
removing arm64_loc_macbookpro_18.4_01_macos_26_vm_a from divramod/hal2"""
DAEMON = """2026-10-16T05:50:00.000001Z  INFO hal2_daemon: started
2026-10-16T05:55:35.515281Z  WARN hal2_vm_node::lazy: vm: is arm64_loc_vm_a busy? /opt/homebrew/bin/gh exited with code 1: gh: Requires authentication (HTTP 401)
2026-10-16T05:56:00.100000Z  WARN hal2_ci_supervisor: ci supervisor: mac_vm: could not look: GitHub's jobs: /opt/homebrew/bin/gh exited with code 1: gh: Not Found (HTTP 404)
2026-10-16T05:57:00.200000Z  WARN hal2_node_exporter: node exporter: pull: /opt/homebrew/bin/gh exited with code 1: gh: Not Found (HTTP 404)
2026-10-16T06:02:55.000000Z  INFO hal2_vm_node::runner: vm: runner hal2/ci-runner-macos instance 0 stops: its job ended
"""
VMS = {"node": None, "vms": [{"id": "hal2/ci-runner-macos", "state": "stopped", "runner": True,
                              "runner_enabled": True, "job": "", "problem": ""}]}


def task_name(start):
    """A UUIDv7 task id starting at `start`, as hal2's task logs are named."""
    h = f"{int(start.timestamp() * 1000):012x}"
    return f"{h[:8]}-{h[8:]}-7000-8000-000000000000"


def task(start, end, text):
    return {"name": task_name(start), "start": start, "end": end, "lines": text.splitlines()}


def ctx(**kw):
    base = {"now": NOW, "daemon": [], "journal": None, "tasks": [], "pmset": None, "vm": VMS["vms"][0]}
    base.update(kw)
    return base


def at(hh, mm, ss=0):
    return datetime(2026, 10, 16, hh, mm, ss, tzinfo=UTC)


class Sources(unittest.TestCase):
    def test_task_start_is_the_uuid7_time(self):
        self.assertEqual(sources.task_start("01a14347-831d-7138-81fd-261636c8c1e5"),
                         datetime(2026, 10, 16, 5, 55, 22, 525000, tzinfo=UTC))
        self.assertIsNone(sources.task_start("not-a-uuid.log"))

    def test_tail_since_reads_only_the_window_of_a_big_log(self):
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
            for minute in range(600):
                f.write(f"{(at(0, 0) + timedelta(minutes=minute)).isoformat()[:19]}.000000Z  INFO x: line {minute}\n")
        lines = sources.tail_since(f.name, at(9, 0), chunk=512)
        self.assertLess(len(lines), 600)
        kept = sources.stamped(lines, at(9, 0), at(9, 5))
        self.assertEqual([l.split()[-1] for _, l in kept], ["540", "541", "542", "543", "544", "545"])
        self.assertIsNone(sources.tail_since(f.name + ".gone", at(9, 0)))

    def test_runner_tasks_keep_runner_logs_of_the_window(self):
        with tempfile.TemporaryDirectory() as d:
            for start, text in ((at(5, 56, 28), TASK_DEAD_BOOT), (at(5, 0), TASK_GOOD), (at(5, 58), "build log")):
                p = Path(d) / f"{task_name(start)}.log"
                p.write_text(text)
                end = (start + timedelta(minutes=7)).timestamp()
                os.utime(p, (end, end))
            found = sources.runner_tasks(d, at(5, 30), NOW)
        self.assertEqual([t["start"].replace(microsecond=0) for t in found], [at(5, 56, 28)])
        self.assertEqual(found[0]["lines"][-1].split()[0], "removing")

    def test_pmset_lines_in_utc(self):
        text = ("2026-10-16 05:58:19 +0200 Sleep               \tEntering Sleep state due to 'Maintenance Sleep'\n"
                "2026-10-16 07:44:30 +0200 Wake                \tDarkWake to FullWake\n"
                "2026-10-16 07:45:00 +0200 Assertions          \tPID 1(caffeinate) Created\n")
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(text)
        events = sources.pmset_events(f.name, at(3, 0), at(6, 0))
        self.assertEqual([(t, k) for t, k, _ in events], [(at(3, 58, 19), "Sleep"), (at(5, 44, 30), "Wake")])

    def test_gh_jobs_keep_unfinished_jobs_the_vm_can_take(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("1\tqueued\tself-hosted,macOS,ARM64,hal2,mac-vm-a\n2\tcompleted\tself-hosted,macOS,mac-vm-a\n"
                    "3\tqueued\tself-hosted,macOS,mac-host-a\n4\tin_progress\tself-hosted,mac-vm-a\n")
        jobs = sources.gh_jobs(f.name, sources.LABELS)
        self.assertEqual([j[1] for j in jobs], ["1", "4"])

    def test_vm_row(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            json.dump(VMS, f)
        self.assertEqual(sources.vm_row(f.name)["state"], "stopped")
        self.assertIsNone(sources.vm_row(f.name, "hal2/nope"))


class Cases(unittest.TestCase):
    def daemon(self):
        return sources.stamped(DAEMON.splitlines(), at(5, 0), NOW)

    def test_incident_2026_10_16_gives_cases_1_and_2(self):
        tasks = [task(at(5, 55, 22), at(5, 55, 35), TASK_401), task(at(5, 56, 28), at(6, 3, 15), TASK_DEAD_BOOT)]
        lines = self.daemon()
        found = signatures.find(ctx(daemon=[x for x in lines if sources.is_vm(x[1])], daemon_all=lines,
                                    tasks=tasks))
        self.assertEqual([(f["case"], f["slug"]) for f in found], [(1, "gh-auth"), (2, "slow-boot")])
        self.assertIn("1 lines HTTP 401, 2 lines HTTP 404", found[0]["detail"])
        self.assertIn(task_name(at(5, 55, 22))[:8], found[0]["detail"])
        self.assertIn("boot 402s", found[1]["detail"])

    def test_a_start_hung_at_copy_in_is_dead_only_old_and_with_the_vm_down(self):
        hung = task(at(5, 56, 28), at(5, 56, 31), TASK_HUNG)
        self.assertEqual([f["slug"] for f in signatures.find(ctx(tasks=[hung]))], ["dead-start"])
        running = dict(VMS["vms"][0], state="running")
        self.assertEqual(signatures.find(ctx(tasks=[hung], vm=running)), [])
        self.assertEqual(signatures.find(ctx(tasks=[hung], now=at(5, 59))), [])

    def test_a_good_job_is_no_case(self):
        self.assertEqual(signatures.find(ctx(tasks=[task(at(5, 0), at(5, 3), TASK_GOOD)])), [])

    def test_the_watchdog_lines(self):
        lines = sources.stamped([
            "2026-10-16T05:57:00.000000Z  WARN hal2_ci_supervisor: ci supervisor: mac vm runner restarted (1 of 3)",
            "2026-10-16T06:05:00.000000Z  WARN hal2_ci_supervisor: ci supervisor: mac vm: start still not online"],
            at(5, 0), NOW)
        self.assertEqual([f["slug"] for f in signatures.find(ctx(daemon=lines))],
                         ["watchdog-restart", "watchdog-gave-up"])

    def test_a_sleep_during_a_runner_job(self):
        job = task(at(1, 50), at(2, 10), TASK_GOOD)
        during = ctx(tasks=[job], pmset=[(at(2, 0), "Sleep", "Maintenance Sleep"), (at(2, 5), "Wake", "x")])
        self.assertEqual([f["slug"] for f in signatures.find(during)], ["slept"])
        self.assertEqual(signatures.find(ctx(tasks=[job], pmset=[(at(3, 0), "Sleep", "")])), [])

    def test_a_wake_soon_after_a_park_once_from_log_and_journal(self):
        park = "ci supervisor: mac vm runner off (park), 0 jobs waiting"
        wake = "ci supervisor: mac vm runner on (wake), 1 jobs waiting"
        daemon = [(at(5, 55, 40), f"2026-10-16T05:55:40.1Z  INFO hal2_ci_supervisor: {park}"),
                  (at(6, 4), f"2026-10-16T06:04:00.1Z  INFO hal2_ci_supervisor: {wake}")]
        journal = [(at(5, 55, 41), f"2026-10-16T05:55:41Z {park[15:]}"), (at(6, 4), f"2026-10-16T06:04:00Z {wake[15:]}")]
        found = signatures.find(ctx(daemon=daemon, journal=journal))
        self.assertEqual([(f["case"], f["slug"]) for f in found], [(4, "park-wake")])
        late = [(at(5, 0), daemon[0][1]), daemon[1]]
        self.assertEqual(signatures.find(ctx(daemon=late)), [])

    def test_labels_the_config_lacks(self):
        line = ("2026-10-15T20:00:00.0Z  WARN hal2_ci_supervisor: ci supervisor: mac vm: jobs wait for labels the "
                "VM's config (mac_vm.labels) lacks: mac-vm-a: never woken for them")
        found = signatures.find(ctx(daemon=[(at(5, 0), line)]))
        self.assertEqual([(f["case"], f["slug"]) for f in found], [(5, "labels")])

    def test_a_runner_github_still_holds_with_a_dead_job(self):
        refused = ("registering arm64_loc_macbookpro_18.4_01_macos_26_vm_a on divramod/hal2\n/opt/homebrew/bin/gh exited "
                   "with code 1: gh: Bad request - Runner arm64_loc_macbookpro_18.4_01_macos_26_vm_a is currently running "
                   "a job and cannot be deleted. (HTTP 422)\n")
        tasks = [task(at(5, 0), at(5, 0, 2), refused), task(at(5, 1), at(5, 1, 2), refused)]
        found = signatures.find(ctx(tasks=tasks))
        self.assertEqual([(f["case"], f["slug"]) for f in found], [(6, "held-runner")])
        self.assertIn("2 runner tasks", found[0]["detail"])
        stand_in = task(at(5, 2), at(5, 9), "registering x on o/r\nx still holds a job on GitHub: registering x_1 instead\n")
        self.assertEqual([f["slug"] for f in signatures.find(ctx(tasks=[stand_in]))], ["stand-in"])


    def test_a_watchdog_restart_that_tore_down_a_running_job(self):
        # The incident of 2026-10-17 00:06:38 (land run 38984579934): the restart 3 s into c4-01-bash-test.
        killed = task(at(0, 5, 27), at(0, 6, 41), "registering x on o/r\n2026-10-17 00:06:35Z: Running job: c4-01-bash-test\n"
                      "command: 35.1s\n$ tart delete y\nremoving x from o/r\n")
        restart = [(at(0, 6, 38), "WARN hal2_ci_supervisor: ci supervisor: mac vm runner restarted (off, on), attempt 1")]
        found = [f for f in signatures.find(ctx(tasks=[killed], daemon=restart)) if f["case"] == 7]
        self.assertEqual([f["slug"] for f in found], ["watchdog-kill"])
        self.assertIn("c4-01-bash-test", found[0]["detail"])
        ended = task(at(0, 5, 27), at(0, 6, 0), "Running job: a\n")  # ended before the restart: no kill
        self.assertEqual([f for f in signatures.find(ctx(tasks=[ended], daemon=restart)) if f["case"] == 7], [])

class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        (d / "tasks").mkdir()
        for start, end, text in ((at(5, 55, 22), at(5, 55, 35), TASK_401),
                                 (at(5, 56, 28), at(6, 3, 15), TASK_DEAD_BOOT)):
            p = d / "tasks" / f"{task_name(start)}.log"
            p.write_text(text)
            os.utime(p, (end.timestamp(), end.timestamp()))
        (d / "daemon.log").write_text(DAEMON)
        (d / "vms.json").write_text(json.dumps(VMS))
        (d / "pmset.txt").write_text("2026-10-16 07:58:19 +0200 Sleep               \tMaintenance Sleep\n")
        (d / "tart.txt").write_text("Source Name State\nlocal  hal2-ci-runner-linux-ubuntu-26.04 stopped\n")
        (d / "gh.txt").write_text("7\tqueued\tself-hosted,macOS,ARM64,hal2,mac-vm-a\n")
        self.flags = ["--daemon-log", str(d / "daemon.log"), "--tasks-dir", str(d / "tasks"),
                      "--journal", str(d / "none.log"), "--pmset-log-file", str(d / "pmset.txt"),
                      "--vms-json", str(d / "vms.json"), "--tart-list", str(d / "tart.txt"),
                      "--gh-jobs", str(d / "gh.txt")]

    def tearDown(self):
        self.dir.cleanup()

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = evidence.main(list(argv))
        return code, out.getvalue()

    def test_doctor_finds_the_incident_in_its_window(self):
        code, out = self.run_main("doctor", "--now", "2026-10-16T06:10:00Z", *self.flags)
        self.assertEqual(code, 0)
        self.assertIn("case 1 gh-auth", out)
        self.assertIn("case 2 slow-boot", out)
        self.assertIn("case 3 slept", out)
        self.assertIn("3 finding(s) in the last 2 h", out)

    def test_doctor_default_window_is_two_hours(self):
        code, out = self.run_main("doctor", "--now", "2026-10-16T08:30:00Z", *self.flags)
        self.assertEqual((code, out.strip()), (0, "no case in the last 2 h"))
        code, out = self.run_main("doctor", "--now", "2026-10-16T08:30:00Z", "--hours", "3", *self.flags)
        self.assertIn("case 2 slow-boot", out)

    def test_doctor_json(self):
        code, out = self.run_main("doctor", "--json", "--now", "2026-10-16T06:10:00Z", *self.flags)
        self.assertEqual([f["case"] for f in json.loads(out)["findings"]], [1, 2, 3])

    def test_show_prints_every_source(self):
        code, out = self.run_main("show", "--now", "2026-10-16T06:10:00Z", *self.flags)
        self.assertEqual(code, 0)
        for needle in ('"state": "stopped"', "hal2-ci-runner-linux", "boot: 402.4s", "hal2_vm_node::lazy",
                       "(no journal yet)", "05:58:19 UTC Sleep", "run - job 7 queued", "case 2 slow-boot"):
            self.assertIn(needle, out)
        self.assertNotIn("node exporter", out.split("== daemon log")[1].split("==")[0])

    def test_capture_writes_files_and_a_readme(self):
        target = Path(self.dir.name) / "incident"
        code, _ = self.run_main("capture", "--out", str(target), "--now", "2026-10-16T06:10:00Z", *self.flags)
        self.assertEqual(code, 0)
        names = {p.name for p in target.iterdir()}
        self.assertTrue({"README.md", "vms.json", "daemon.log", "pmset.txt", "doctor.txt", "tasks"} <= names)
        self.assertEqual(len(list((target / "tasks").iterdir())), 2)
        self.assertIn("`daemon.log`", (target / "README.md").read_text())


class Selfcheck(unittest.TestCase):
    def test_drift_and_ok(self):
        with tempfile.TemporaryDirectory() as repo:
            src = Path(repo) / "code/rust/libs/hal2-ci-supervisor/src"
            src.mkdir(parents=True)
            (src / "config.rs").write_text("pub park_after: u64,\n")
            (src / "events.rs").write_text('"' + '" "'.join(signatures.FRAGMENTS) + '" "kept"')
            skill = Path(repo) / "SKILL.md"
            skill.write_text("`code/rust/libs/hal2-ci-supervisor/src/config.rs` `code/rust/libs/hal2-vm/src/gone.rs`"
                             " `code/rust/libs/hal2-ci-supervisor/src/checks/vm_watch*.rs`\n"
                             "Keep the `<!-- strings -->` block literal.\n"
                             "<!-- strings -->\n`kept` `vanished line`\n<!-- /strings -->\n"
                             "<!-- keys -->\n`park_after` `max_restarts`\n<!-- /keys -->\n")
            real, evidence.SKILL_MD = evidence.SKILL_MD, skill
            try:
                code, out = Cli.run_main(self, "selfcheck", "--repo", repo)
            finally:
                evidence.SKILL_MD = real
        self.assertEqual(code, 1)
        for needle in ("gone.rs", "vm_watch*.rs", "`vanished line`", "`max_restarts`"):
            self.assertIn(needle, out)
        for kept in ("config.rs\n", "`kept`", "`park_after`", "mac kept awake"):
            self.assertNotIn(f"DRIFT {kept}", out)
        self.assertEqual(out.count("DRIFT"), 4)


if __name__ == "__main__":
    unittest.main()
