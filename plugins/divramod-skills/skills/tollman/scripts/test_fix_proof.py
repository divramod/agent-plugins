"""Hal2 plan 0522 step 3 (D5): fix_proof.py's parts without a farm: the jobs an order names, the green lines of an
answer, the verdict of a proof's result, the proof worktree and the config the proof's pretest gets. The orders'
round trip (refused and accepted acks) is test_orders.py's `Proof`."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import fix_proof
import pretest
import train_state

CFG = {"budget": 180, "parallel": 3, "jobs": ["python-lint", "bash-lint", "ts-lint"], "groups": {"ts-lint": "ts"}}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fix-proof-"))
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)])
        for patch in (mock.patch.object(train_state, "folder", return_value=self.tmp / "state"),
                      mock.patch.object(fix_proof, "light_jobs", return_value=(CFG, CFG["jobs"])),
                      mock.patch.object(fix_proof, "known_jobs",
                                        return_value={*CFG["jobs"], "rust-test", "leak-scan", "stack-test"})):
            patch.start()
            self.addCleanup(patch.stop)
        (self.tmp / "code/bash/scripts/gate").mkdir(parents=True)
        (self.tmp / fix_proof.LINT_JOBS).write_text("# the lint jobs\nbash-lint\nleak-scan\npython-lint\n")


class Named(Case):
    def test_ci_names_are_bared_and_the_folded_lint_is_its_light_lint_jobs(self):
        top = str(self.tmp)
        self.assertEqual(fix_proof.named(top, "d1-01-rust-test: thread panicked"), ["rust-test"])
        self.assertEqual(fix_proof.named(top, "linux / rust-test, c2-03-lint"), ["rust-test", "bash-lint",
                                                                                 "python-lint"])
        self.assertEqual(fix_proof.named(top, "its test fails", "ts-lint, bash-lint, suspects: 07"),
                         ["ts-lint", "bash-lint"], "the order's why names none: the train's red")
        self.assertEqual(fix_proof.named(top, "bash-lint: x", "ts-lint"), ["bash-lint"], "the order's own first")
        self.assertEqual(fix_proof.named(top, "nothing here"), [])

    def frames(self):
        folder = self.tmp / fix_proof.GATE_JOBS
        folder.mkdir(parents=True)
        for job, frame in (("python-lint", "python-linux"), ("ts-lint", "ts-linux"), ("rust-test", "rust-linux"),
                           ("leak-scan", "leak-scan"), ("bash-lint", "bash-linux")):
            (folder / f"{job}.sh").write_text(f"#!/usr/bin/env bash\n# lane: linux\n# frame: {frame}\n")
        (folder / "python-test.sh").write_text("# phase: test\n# frame: python-linux\n# frame: other\n")

    def test_a_red_frame_job_is_the_gate_jobs_of_its_steps(self):
        """Plan 0728 D22: `c1-06-python-linux` is a job per frame; the proof needs its steps' gate jobs (python-test is
        no known job here, so it is left out; the second `# frame:` line of a file is none)."""
        self.frames()
        top = str(self.tmp)
        self.assertEqual(fix_proof.frames(top)["python-linux"], ["python-lint", "python-test"])
        self.assertNotIn("leak-scan", fix_proof.frames(top), "a job that is its own frame is a gate job already")
        self.assertEqual(fix_proof.named(top, "c1-06-python-linux: x.py:1:1: E501"), ["python-lint"])
        self.assertEqual(fix_proof.named(top, "python-linux, ts-linux"), ["python-lint", "ts-lint"])
        self.assertEqual(fix_proof.named(top, "c1-07-ts-linux"), ["ts-lint"])
        self.assertEqual(fix_proof.named(top, "c1-04-rust-linux, c2-02-leak-scan"), ["rust-test", "leak-scan"])
        self.assertEqual(fix_proof.named(top, "c1-07-ts-linux: ts-lint failed"), ["ts-lint"], "named once")

    def test_a_step_the_text_names_wins_over_its_frame(self):
        self.frames()
        self.assertEqual(fix_proof.named(str(self.tmp), "python-linux: python-lint failed, bash-linux"),
                         ["python-lint", "bash-lint"])
        self.assertEqual(fix_proof.named(str(self.tmp), "c2-02-leak-scan red"), ["leak-scan"])


class Verdict(Case):
    O = {"id": "07-fix-1", "jobs": ["python-lint", "rust-test"]}
    SHA = "a" * 40

    def verdict(self, note="", **o):
        return fix_proof.verdict(str(self.tmp), str(self.tmp), {**self.O, **o}, self.SHA, note)

    def result(self, **doc):
        fix_proof.write(str(self.tmp), self.O["id"], self.SHA, doc)

    def test_a_heavy_job_needs_its_line_on_the_sha_an_order_naming_none_any_line(self):
        self.assertEqual(self.verdict()[0], "no")
        self.assertIn("no proof for rust-test", self.verdict()[1])
        self.assertIn("no proof for rust-test", self.verdict(f"gate: rust-test green at {'b' * 12}")[1],
                      "a line on another commit")
        self.assertEqual(self.verdict(f"gate: rust-test green at {'a' * 12}")[0], "start", "then the light proof")
        self.assertIn("carries no `gate: <job> green at", self.verdict(jobs=[])[1])
        self.assertEqual(self.verdict(f"fixed: gate: ts-test green at {'a' * 9}", jobs=[]), ("ok", ""))

    def test_the_red_check_s_own_green_proves_it_never_the_whole_job(self):
        """Plan 0610 D6 (the user: "only what was red"): the failing check's own green line is the proof; the ask
        names the smallest form and never the whole gate job."""
        sha = "a" * 12
        self.assertNotIn("gate/main.sh", self.verdict()[1], "never the whole job asked")
        self.assertIn(f"green: <that check> at {sha}", self.verdict()[1])
        test = f"done fixed {sha}: green: cargo nextest run -p hal2-git -E 'test(queue_ready)' at {sha}"
        self.assertEqual(self.verdict(test)[0], "start", "a check naming no job proves the heavy job; then the light")
        self.assertEqual(self.verdict(f"green: rust-test hal2_git::queue::ready at {sha}")[0], "start")
        self.assertIn("no proof for rust-test", self.verdict(f"green: stack-test boot at {sha}",
                                                            jobs=["rust-test", "stack-test"])[1],
                      "a check naming another heavy job proves only that one")
        self.assertIn("no proof for rust-test", self.verdict(f"green: the build at {'b' * 12}")[1], "another commit")
        self.assertEqual(self.verdict(f"green: the build at {sha}", jobs=[]), ("ok", ""))
        self.assertTrue(fix_proof.has_line(test) and fix_proof.has_line(f"gate: x green at {sha}"))
        self.assertFalse(fix_proof.has_line(f"done fixed {sha}"))

    def test_the_light_proof_s_result_decides(self):
        line, light = f"gate: rust-test green at {self.SHA}", {"jobs": ["python-lint"]}
        self.assertEqual(self.verdict(line)[0], "start", "no result yet")
        self.result(state="running", attempt=1, pid=4711)
        with mock.patch.object(fix_proof.mtm_scan, "pid_alive", return_value=True):
            self.assertEqual(self.verdict(line)[0], "wait")
            self.assertTrue(fix_proof.busy(str(self.tmp)))
        self.assertEqual(self.verdict(line)[0], "start", "its process is gone: again")
        self.result(state="green", attempt=1)
        self.assertEqual(self.verdict(line), ("ok", ""))
        self.result(state="red", attempt=1, errors={"python-lint": "x.py:1:1: E501"})
        self.assertEqual(self.verdict(**light), ("no", f"red on {'a' * 12} in the tollman's own run: python-lint: "
                                                       "x.py:1:1: E501"))
        self.result(state="incomplete", attempt=1, why="the budget cut python-lint")
        self.assertEqual(self.verdict(**light)[0], "start", "an incomplete proof runs again")
        self.result(state="incomplete", attempt=fix_proof.TRIES, why="the budget cut python-lint")
        self.assertIn(f"({fix_proof.TRIES} tries)", self.verdict(**light)[1])
        self.result(state="skipped", attempt=1, why="gate: tool missing: ruff")
        self.assertIn("tool missing: ruff (the tollman's session decides)", self.verdict(**light)[1])
        self.result(state="refused", attempt=1, why="aaaaaaaaaaaa is not on origin/07-train-fix")
        self.assertEqual(self.verdict(**light), ("no", "aaaaaaaaaaaa is not on origin/07-train-fix"))

    def test_old_results_go_the_proof_worktree_stays(self):
        self.result(state="green", attempt=1)
        folder = self.tmp / "state" / fix_proof.FOLDER
        (folder / fix_proof.TREE).mkdir()
        fix_proof.prune(folder, now=1e12)
        self.assertEqual([p.name for p in folder.iterdir()], [fix_proof.TREE])


class Worktree(Case):
    def test_the_proof_worktree_is_made_switched_and_made_again(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        for n in ("1", "2"):
            (repo / "f.txt").write_text(n)
            git(repo, "add", "f.txt")
            git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", n)
        first, second = git(repo, "rev-parse", "HEAD~1"), git(repo, "rev-parse", "HEAD")
        tree = self.tmp / "state" / fix_proof.FOLDER / fix_proof.TREE
        self.assertEqual(fix_proof.checkout(str(repo), tree, first), "")
        self.assertEqual(git(tree, "rev-parse", "HEAD"), first)
        (tree / "f.txt").write_text("a job's change")
        self.assertEqual(fix_proof.checkout(str(repo), tree, second), "")
        self.assertEqual((git(tree, "rev-parse", "HEAD"), (tree / "f.txt").read_text()), (second, "2"))
        subprocess.run(["rm", "-rf", str(tree)], check=True)  # the cache deleted: made again
        self.assertEqual(fix_proof.checkout(str(repo), tree, first), "")
        self.assertIn("does not check out", fix_proof.checkout(str(repo), tree, "f" * 40))

    def test_the_proof_runs_only_the_order_s_light_jobs_with_their_groups(self):
        seen = {}

        def fake(top, state, base, log, config=None, gate=None, progress=None):
            seen.update(top=top, config=Path(config).read_text())
            return {"result": "green", "jobs": [], "why": "", "errors": {}}

        with mock.patch.object(fix_proof, "checkout", return_value=""), mock.patch.object(pretest, "pretest", fake):
            r = fix_proof.prove(str(self.tmp), str(self.tmp), ["python-lint", "ts-lint"], "a" * 40, self.tmp / "l")
        (self.tmp / "c.toml").write_text(seen["config"])
        cfg, _ = pretest.read_config(self.tmp / "c.toml")
        self.assertEqual((r["result"], cfg["jobs"], cfg["groups"], cfg["budget"]),
                         ("green", ["python-lint", "ts-lint"], {"ts-lint": "ts"}, 180))
        self.assertTrue(seen["top"].endswith("cache/proof/.proof-tree"))


if __name__ == "__main__":
    unittest.main()
