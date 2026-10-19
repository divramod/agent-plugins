"""prune.py run (executor.py; hal2 plan 0377 step 5): each action on a scratch farm behind fake CLIs (fake_clis.py),
the proof again before each action, the farm lock, the dry run and the output as workflow commands (RN1-RN10,
PR1-PR4, PR7, PR10, PR13-PR17, PR21, PR24, PR25). Nothing outside the scratch farm is touched."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import fake_clis
import halfway
import prune_act
import store
from fake_clis import jobs, parse
from test_farmer import git

SIX = ["facts", "stale-pointers", "phase-1", "phase-2", "phase-3", "report"]
SHORT = {"free_gb": 100.0, "used_pct": 91.0, "total_gb": 1000.0}
GOAL = {"free_gb": 300.0, "used_pct": 70.0, "total_gb": 1000.0}


class Remove(fake_clis.Farm):
    def test_rn1_pr1_a_free_field_is_removed_in_its_step_and_the_run_has_the_six_jobs(self):
        self.add("23")
        self.free = [10**12, 10**12 + 5 * 10**9]
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        self.assertEqual(jobs(lines), SIX)
        steps = parse(lines)["phase-1"]
        self.assertEqual([(s[0], s[1]) for s in steps], [("field 23", "success")])
        self.assertIn("removed 23: 5.0 GB freed, free by the proof", steps[0][2])
        self.assertFalse((self.base / "23").exists())
        self.assertEqual(self.calls(), [["worktree", "remove", "23", "--remote"]])
        self.assertEqual(halfway.journal(str(self.main)), {}, "the journal is dropped once the command ended")
        self.assertEqual(lines[-1], "prune: 1 actions, 5.0 GB freed, 0 asks")

    def test_rn3_pr12_a_fine_disk_skips_phases_2_and_3_with_one_line(self):
        self.add("23")
        _, lines = self.prune()
        out = parse(lines)
        self.assertEqual((out["phase-2"], out["phase-3"]), ([], []))
        self.assertIn("skipped: disk fine (400 GB free)", lines)

    def test_pr2_an_idle_session_is_stopped_by_signal_first_a_draft_skips_the_removal(self):
        self.add("23")
        self.add("24")
        self.feed(agents=[self.agent("23", minutes_ago=60), self.agent("24", minutes_ago=60)])
        refusals = {"%23": None, "%24": "a draft in its prompt"}
        with mock.patch.object(prune_act, "stop", side_effect=lambda main, pane: refusals[pane]) as stop:
            code, lines = self.prune()
        self.assertEqual(code, 0)
        self.assertEqual(sorted(c.args[1] for c in stop.call_args_list), ["%23", "%24"])
        steps = {s[0]: s for s in parse(lines)["phase-1"]}
        self.assertEqual(steps["field 23"][1], "success")
        self.assertEqual(steps["field 24"][1], "skipped")
        self.assertIn("skipped 24: %24: not stopped: a draft in its prompt", steps["field 24"][2])
        self.assertTrue((self.base / "24").exists())

    def test_pr3_an_unpushed_commit_leaves_the_field(self):
        path = self.add("25")
        git(path, "commit", "-q", "--allow-empty", "-m", "not pushed")
        code, lines = self.prune()
        self.assertEqual((code, parse(lines)["phase-1"]), (0, []))
        self.assertIn("skipped: no free field", lines)
        self.assertTrue(path.exists())
        self.assertEqual(self.calls(), [])

    def test_pr21_the_proof_runs_again_just_before_the_action(self):
        self.add("23")
        real = fake_clis.facts.collect
        seen = []

        def collect(main, only=None, **kw):
            seen.append(only)
            if len(seen) == 2:  # after the plan: its agent starts working
                self.feed(agents=[self.agent("23", state="working", minutes_ago=0)])
            return real(main, only=only, **kw)

        with mock.patch.object(fake_clis.facts, "collect", side_effect=collect):
            code, lines = self.prune()
        self.assertEqual(code, 0)
        (step,) = parse(lines)["phase-1"]
        self.assertEqual(step[1], "skipped")
        self.assertIn("skipped 23: its agent %23 is working", step[2])
        self.assertTrue((self.base / "23").exists())
        self.assertEqual(self.calls(), [])

    def test_rn7_a_failed_action_fails_its_step_later_jobs_run_and_the_exit_is_1(self):
        self.add("23")
        self.add("24")
        self.feed(fail_remove=["23"])
        code, lines = self.prune()
        self.assertEqual(code, 1)
        self.assertEqual(jobs(lines), SIX)
        steps = {s[0]: s[1] for s in parse(lines)["phase-1"]}
        self.assertEqual(steps, {"field 23": "failure", "field 24": "success"})
        self.assertIn("failed: 23", lines)
        self.assertTrue((self.base / "23").exists())

    def test_field_limits_the_run_to_the_named_fields(self):
        self.add("23")
        self.add("24")
        _, lines = self.prune("24")
        self.assertEqual([s[0] for s in parse(lines)["phase-1"]], ["field 24"])
        self.assertTrue((self.base / "23").exists())


class Servant(fake_clis.Farm):
    def setUp(self):
        super().setUp()
        lead = self.add("02")
        git(lead, "commit", "-q", "--allow-empty", "-m", "the foreman's plan")
        git(lead, "push", "-q", "origin", "02")
        for slot in ("31", "32"):
            path = self.add(slot, "origin/02")
            git(path, "commit", "-q", "--allow-empty", "-m", f"step of {slot}")
            git(path, "push", "-q", "origin", slot)
            (path / "plans").mkdir()
            (path / "plans/LEAD").write_text("02 0013-x 4\n")
            os.utime(path / "plans/LEAD", (time.time() - 7200,) * 2)
        git(lead, "merge", "-q", "--no-ff", "-m", "merge 31", "origin/31")
        git(lead, "push", "-q", "origin", "02")

    def remote(self, name):
        return git_out(self.main, "ls-remote", "origin", f"refs/heads/{name}")

    def test_pr7_a_servant_in_its_foremans_branch_is_forced_out_and_origin_nn_deleted_pr8_the_other_an_ask(self):
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        steps = {s[0]: s for s in parse(lines)["phase-1"]}
        self.assertEqual(steps["field 31"][1], "success")
        self.assertEqual(self.calls(), [["worktree", "remove", "31", "--force"]])
        self.assertFalse(self.remote("31"))
        self.assertEqual(steps["field 32"][1], "skipped")
        self.assertIn("ask the foreman of field 02 about field 32", steps["field 32"][2][0])
        self.assertTrue((self.base / "32").exists() and self.remote("32"))


class Trim(fake_clis.Farm):
    def target(self, slot, rel="code/rust/target"):
        d = self.base / slot / rel
        d.mkdir(parents=True)
        (d / "x.o").write_text("x" * 100)
        return d

    def test_pr17_a_free_keeper_is_mucked_out_pr13_pr24_d24_then_trimmed_when_the_disk_is_short(self):
        (self.main / ".hal").mkdir(exist_ok=True)
        (self.main / ".hal/cleanup").write_text("target\n!code/rust/target\n")  # hal2's: the Rust target kept
        git(self.main, "add", ".hal/cleanup")
        git(self.main, "commit", "-qm", "cleanup rules")
        git(self.main, "push", "-q", "origin", "main")
        self.add("03")
        plain, kept = self.target("03", "target"), self.target("03")
        (self.main / ".hal/prune.toml").write_text('[phases]\ntrim = ["code/rust/target"]\n')
        self.disk = dict(SHORT)
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        out = parse(lines)
        self.assertEqual([(s[0], s[1]) for s in out["phase-1"]], [("field 03", "success")])
        self.assertFalse(plain.exists(), "mucked out by the cleanup skill's own set")
        self.assertEqual([(s[0], s[1]) for s in out["phase-2"]], [("field 03", "success")])
        self.assertFalse(kept.exists(), "trimmed by the config's path (D24)")
        self.assertTrue((self.base / "03").is_dir(), "00-09 are never removed")
        self.assertEqual(self.calls(), [])

    def test_pr13_pr14_phase_2_trims_biggest_first_until_the_goal_pr15_phase_3_then_skipped(self):
        for slot in ("25", "26"):
            path = self.add(slot)
            git(path, "commit", "-q", "--allow-empty", "-m", "work")  # not free: phase 2's
        self.target("25")
        self.target("26")
        (self.base / "26/code/rust/target/big.o").write_text("x" * 100_000)
        git(self.add("04"), "commit", "-q", "--allow-empty", "-m", "work")  # live, idle, not free: phase 3's
        self.target("04")
        self.feed(agents=[self.agent("04", minutes_ago=90)])
        reads = iter([SHORT, SHORT, SHORT, GOAL])  # run start, phase 2 start, before 26, before 25
        self.disk = SHORT
        with mock.patch.object(fake_clis.facts, "disk", side_effect=lambda main: dict(next(reads, GOAL))):
            code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        out = parse(lines)
        self.assertEqual([(s[0], s[1]) for s in out["phase-2"]], [("field 26", "success")])
        self.assertIn("stopped: goal met (300 GB free, 70% used)", lines)
        self.assertTrue((self.base / "25/code/rust/target").exists())
        self.assertEqual(out["phase-3"], [])
        self.assertTrue(any(x.startswith("skipped: goal met") for x in lines))

    def test_pr10_a_running_build_skips_the_trim(self):
        self.add("03")
        self.target("03", "target")
        with mock.patch.object(prune_act, "cleanup", side_effect=lambda path, *a: (1, "4242 cargo build") if a == ("busy",)
                               else (0, "")) as cleanup:
            status, text = prune_act.clean({"path": str(self.base / "03")}, None)
        self.assertEqual(status, "skipped")
        self.assertIn("a build or test runs in it: 4242 cargo build", text)
        self.assertEqual(len(cleanup.call_args_list), 1)


class Stale(fake_clis.Farm):
    def test_pr4_a_stale_pointer_is_cleared_logged_and_the_field_removed_in_phase_1(self):
        path = self.add("13")
        (path / "plans").mkdir()
        (path / "plans/CURRENT_PLAN").write_text("0149-x\n")
        self.feed(plans={"0149-x": {"state": "done"}})
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        out = parse(lines)
        (step,) = out["stale-pointers"]
        self.assertEqual((step[0], step[1]), ("field 13", "success"))
        self.assertEqual(step[2][0], "cleared CURRENT_PLAN 0149-x (finished)")
        self.assertEqual(step[2][1], "new proof: free")
        self.assertEqual([(s[0], s[1]) for s in out["phase-1"]], [("field 13", "success")])
        self.assertFalse(path.exists())


class DryRun(fake_clis.Farm):
    def test_pr25_rn10_the_same_jobs_and_steps_every_action_would_and_nothing_changes(self):
        self.add("23")
        p13 = self.add("13")
        (p13 / "plans").mkdir()
        (p13 / "plans/CURRENT_PLAN").write_text("0149-x\n")
        self.add("03")
        (self.base / "03/target").mkdir()
        (self.base / "03/target/x.o").write_text("x")
        self.feed(plans={"0149-x": {"state": "done"}})
        self.disk = dict(SHORT)
        before = self.tree()
        code, lines = self.prune(dry=True)
        self.assertEqual(code, 0, lines)
        self.assertEqual(jobs(lines), SIX)
        out = parse(lines)
        self.assertIn("would clear 13", out["stale-pointers"][0][2][0])
        said = [s[2][0] for s in out["phase-1"]]
        self.assertTrue(any(x.startswith("would muck out 03") for x in said), said)
        self.assertTrue(any(x.startswith("would remove 23") for x in said), said)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.calls(), [])
        self.assertIn("planned actions", lines[-1])


class Lock(fake_clis.Farm):
    def test_rn4_a_second_run_is_refused_while_the_first_holds_the_lock(self):
        self.add("23")
        with store.farm_lock(str(self.main)):
            code, lines = self.prune()
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], rf"^already running: pid {os.getpid()} since ")
        self.assertTrue((self.base / "23").exists())

    def test_a_dead_holders_lock_is_taken_over(self):
        self.add("23")
        here = str(Path(__file__).resolve().parent)
        code = (f"import sys, time; sys.path.insert(0, {here!r}); import store\n"
                f"with store.farm_lock({str(self.main)!r}):\n    print('held', flush=True); time.sleep(60)")
        holder = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, env=os.environ)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        code1, lines = self.prune()
        self.assertTrue(lines[0].startswith(f"already running: pid {holder.pid}"))
        holder.send_signal(signal.SIGKILL)
        holder.wait()
        code2, lines = self.prune()
        self.assertEqual((code1, code2), (0, 0))
        self.assertEqual(jobs(lines), SIX)
        self.assertFalse((self.base / "23").exists())


def runs_bin() -> str | None:
    """`hal2-cli-runs` with `exec` (plan 0377 step 2): on PATH, else this checkout's own debug build; None without."""
    here = Path(__file__).resolve()
    root = next((p for p in here.parents if (p / "code/rust/Cargo.toml").is_file()), None)
    for cand in (shutil.which("hal2-cli-runs"), root and str(root / "code/rust/target/debug/hal2-cli-runs")):
        if cand and Path(cand).is_file() and subprocess.run([cand, "help", "exec"], capture_output=True).returncode == 0:
            return cand
    return None


@unittest.skipUnless(runs_bin(), "no hal2-cli-runs with exec (plan 0377 step 2) on PATH or in this checkout")
class RealExec(fake_clis.Farm):
    def test_rn1_rn2_under_hal2_cli_runs_exec_the_six_jobs_and_a_step_per_field(self):
        self.add("23")
        env = {**os.environ, "HAL2_STATE_DIR": str(self.tmp / "runs")}
        prune = str(Path(__file__).resolve().parent / "prune.py")
        p = subprocess.run([runs_bin(), "exec", "--workflow", "prune", "--slot", "99", "--", sys.executable, prune, "run",
                            "--repo", str(self.main)], cwd=self.main, env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        run_id = p.stderr.splitlines()[0].split()[1]
        shown = subprocess.run([runs_bin(), "show", run_id, "--json"], cwd=self.main, env=env, capture_output=True,
                               text=True, check=True)
        run = json.loads(shown.stdout)["run"]
        self.assertEqual((run["workflow"], run["status"]), ("prune", "success"))
        self.assertEqual([j["name"] for j in run["jobs"]], SIX)
        phase1 = next(j for j in run["jobs"] if j["name"] == "phase-1")
        self.assertEqual([(s["name"], s["status"]) for s in phase1["steps"]], [("field 23", "success")])
        self.assertFalse((self.base / "23").exists())


def git_out(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


if __name__ == "__main__":
    unittest.main()
