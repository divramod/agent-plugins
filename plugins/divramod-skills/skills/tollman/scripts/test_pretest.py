"""Hal2 plan 0349 step 28 (D75): the tollman's pretest, pretest.py and its markers (pretest_markers.py), on a
temporary field with a stub gate (pretest_stub.py). The jobs' processes: test_pretest_jobs.py; the train's side:
test_pretest_train.py."""

import contextlib
import io
import json
import time
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import pretest
import pretest_markers
import train_state
from pretest_stub import FieldCase, config, sh


class Pretest(FieldCase):
    def test_green_runs_every_needed_job_and_writes_their_markers(self):
        r = self.run_it(["python-lint", "bash-lint"])
        self.assertEqual((r["result"], self.states(r)),
                         ("green", [("python-lint", "run", "green"), ("bash-lint", "run", "green")]))
        self.assertEqual(sorted(self.stub.ran()), ["bash-lint", "python-lint"])
        self.assertEqual(self.marked(), ["gate-bash-lint-k-bash-lint", "gate-python-lint-k-python-lint"])
        self.assertTrue((self.state / "cache/CACHEDIR.TAG").exists(), "the role folder's cache class")
        self.assertEqual(pretest_markers.MARKERS, Path("cache/pretest"))
        head, base = sh(self.top, "git", "rev-parse", "HEAD"), sh(self.top, "git", "rev-parse", "HEAD~1")
        self.assertEqual((r["base"], r["head"]), (base, head))
        self.assertEqual((self.stub.dir / "env-python-lint").read_text(), f"|{base}|{head}|1\n",
                         "CI's environment, and the gate installs nothing")
        log = self.log.read_text()
        self.assertIn("python-lint: run, green", log)
        self.assertIn("== bash-lint (run, ", log)
        self.assertIn("bash-lint done", log)

    def test_a_marker_present_is_cached_and_not_run(self):
        (pretest_markers.folder(self.state) / "gate-python-lint-k-python-lint").touch()
        r = self.run_it(["python-lint", "bash-lint"])
        self.assertEqual((r["result"], self.states(r)),
                         ("green", [("python-lint", "cached", "green"), ("bash-lint", "run", "green")]))
        self.assertEqual(self.stub.ran(), ["bash-lint"])

    def test_old_markers_go_and_a_marker_write_that_fails_changes_nothing(self):
        folder = pretest_markers.folder(self.state)
        (folder / "gate-old-k").touch()
        pretest_markers.folder(self.state, now=time.time() + (pretest_markers.KEEP_DAYS + 1) * 86400)
        self.assertEqual(list(folder.iterdir()), [])
        with mock.patch.object(Path, "stat", side_effect=FileNotFoundError("raced")):  # another prune took it
            (folder / "gate-x-k").touch()
            pretest_markers.prune(folder)
        with mock.patch.object(Path, "touch", side_effect=OSError("read-only")):
            pretest_markers.mark(folder, "x", "k2")
        self.assertIsNone(pretest_markers.folder(Path("/dev/null")))

    def test_a_red_stays_red_when_the_log_and_markers_cannot_be_written(self):
        self.stub.job("python-lint", "code=1")
        cfg = config(self.tmp / "hal2-pretest.toml", ["python-lint", "bash-lint"])
        with (mock.patch.object(Path, "write_text", side_effect=OSError("disk full")),
              mock.patch.object(Path, "touch", side_effect=OSError("disk full"))):
            r = pretest.pretest(str(self.top), self.state, "HEAD~1", self.log, cfg, self.stub.main)
        self.assertEqual((r["result"], self.log.exists()), ("red", False))

    def test_a_job_the_range_does_not_select_is_not_needed_and_packages_go_to_the_job(self):
        self.stub.selects(["bash-lint"], packages="hal2-git hal2-core")
        r = self.run_it(["python-lint", "bash-lint"])
        self.assertEqual((r["result"], self.states(r)),
                         ("green", [("python-lint", "not needed", None), ("bash-lint", "run", "green")]))
        self.assertTrue((self.stub.dir / "env-bash-lint").read_text().startswith("hal2-git hal2-core|"))

    def test_an_unknown_job_or_a_gate_list_that_fails_makes_the_pretest_skipped(self):
        r = self.run_it(["bash-lint", "no-such-job"])
        self.assertEqual((r["result"], self.states(r)),
                         ("skipped", [("bash-lint", "run", "green"), ("no-such-job", "skipped", None)]))
        self.assertEqual(r["jobs"][1]["why"], "no such gate job")
        self.assertIn("no-such-job: skipped (no such gate job)", self.log.read_text())
        (self.stub.dir / "list-fails").touch()
        r = self.run_it(["bash-lint"])
        self.assertEqual((r["result"], r["jobs"]), ("skipped", []))
        self.assertIn("gate list ended 3", r["why"])

    def test_a_dirty_field_writes_no_marker_and_a_job_that_dirties_it_is_skipped(self):
        (self.top / "a.txt").write_text("changed\n")
        r = self.run_it(["bash-lint"])
        self.assertEqual((r["result"], self.marked()), ("green", []), "the key is HEAD's content, not the tree's")
        sh(self.top, "git", "checkout", "a.txt")
        self.stub.job("bash-lint", f"echo x >>{self.top}/a.txt")
        r = self.run_it(["bash-lint", "python-lint"])
        self.assertEqual((r["result"], self.marked()), ("skipped", []))
        self.assertIn("a job changed tracked files (a.txt)", r["why"])

    def test_no_config_or_no_job_is_no_pretest(self):
        r = pretest.pretest(str(self.top), self.state, "HEAD~1", self.log, self.tmp / "missing.toml", self.stub.main)
        self.assertEqual((r["result"], r["jobs"], r["why"]), ("none", [], "no .github/hal2-pretest.toml"))
        self.assertIn("none (no .github/hal2-pretest.toml)", self.log.read_text())
        (self.tmp / "empty.toml").write_text("budget = 10\n")
        r = pretest.pretest(str(self.top), self.state, "HEAD~1", self.log, self.tmp / "empty.toml", self.stub.main)
        self.assertEqual((r["result"], r["why"]), ("none", "no [[job]] in empty.toml"))
        self.assertEqual(self.stub.calls(), [])

    def test_the_cli_dry_run_keeps_the_tollmans_markers_only_in_its_own_field(self):
        config(self.top / pretest.CONFIG, ["python-lint"])
        self.state.mkdir()

        def dry(own):
            out = io.StringIO()
            with (mock.patch.object(pretest, "GATE", str(self.stub.main)), contextlib.redirect_stdout(out),
                  mock.patch.object(train_state, "folder", return_value=self.state),
                  mock.patch.object(mtm_scan.roles, "slot_dir", return_value=self.top if own else self.tmp / "wm")):
                code = pretest.main(["run", "--repo", str(self.top), "--base", "HEAD~1", "--json"])
            return code, json.loads(out.getvalue())

        code, r = dry(own=False)
        self.assertEqual((code, r["result"], self.states(r), self.marked()),
                         (0, "green", [("python-lint", "run", "green")], []), "a temporary markers folder")
        code, r = dry(own=True)
        self.assertEqual((code, self.marked()), (0, ["gate-python-lint-k-python-lint"]))

    def test_a_plan_that_needs_a_build_ends_skipped_at_once(self):
        """Plan 0490 step 17: a range that changes the change detection needs the checkout's hal2-cli-git, a cold
        build in the train's new field (14 of 15 recorded `gate plan` timeouts, 180 s each): the plan builds nothing
        (HAL2_GATE_NO_BUILD), the pretest is skipped within seconds with that reason and runs no job."""
        (self.stub.dir / "plan-builds").touch()
        began = time.monotonic()
        r = self.run_it(["python-lint", "bash-lint"], budget=60)
        self.assertLess(time.monotonic() - began, 10, "no build, no waiting for the budget")
        self.assertEqual((r["result"], r["jobs"], self.stub.ran()), ("skipped", [], []))
        self.assertIn("the checkout's build is needed (the range changes the detection), not built", r["why"])
        self.assertIn("the train's local phase builds nothing", r["why"])
        self.assertIn("pretest of ", self.log.read_text())
        self.assertFalse((self.stub.dir / "plan-child").exists(), "the plan started no build")


if __name__ == "__main__":
    unittest.main()
