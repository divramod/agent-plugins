"""Hal2 plan 0490 step 9: the pretest's learnings replayed with the stub gate (pretest_stub.py). L27: a red that is
only a test timeout (train 18+02+16+10+23+06: a hal9k-mobile vitest at 9.4 s > 5 s) runs again once; twice it is
red and says load-flaky. L101: a red whose output is dyld's `Library not loaded` for a Homebrew tool (train 16:
protoc and abseil) is the Mac's, skipped, never a car's. L114, L116, L120: every job sees the runner's environment
(CI, GITHUB_ACTIONS, CARGO_INCREMENTAL=0) unless its config says `ci_env = false`."""

import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import pretest
import pretest_jobs
from pretest_stub import FieldCase, config

VITEST = """ FAIL  src/sync.test.ts > sync > merges
Error: Test timed out in 5000ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 Test Files  1 failed | 40 passed (41)
      Tests  1 failed | 311 passed (312)
"""
DYLD = ("dyld[83121]: Library not loaded: /opt/homebrew/opt/abseil/lib/libabsl_die_if_null.2601.dylib\n"
        "  Referenced from: /opt/homebrew/Cellar/protobuf/33.4_1/bin/protoc\n")


def once_then(path: str, first: str, then: str) -> str:
    """A job body: `first` on its first run, `then` after (a counter file beside the stub)."""
    return f'if [[ -f "$here/{path}" ]]; then {then}; else touch "$here/{path}"; {first}; fi'


class Timeouts(FieldCase):
    def test_a_timeout_only_red_runs_again_once_and_a_green_second_run_is_green(self):
        self.stub.job("python-lint", once_then("seen", f"cat <<'X'\n{VITEST}X\ncode=1", "code=0"))
        r = self.run_it(["python-lint", "bash-lint"], parallel=1)
        self.assertEqual((r["result"], self.states(r)),
                         ("green", [("python-lint", "run", "green"), ("bash-lint", "run", "green")]))
        self.assertEqual(self.stub.ran().count("python-lint"), 2)
        self.assertEqual(self.stub.ran()[:2], ["python-lint", "python-lint"], "the rerun goes first in line")
        self.assertIn("Test timed out in 5000ms", self.log.read_text(), "the first run's output is kept")

    def test_a_timeout_twice_is_red_and_says_load_flaky(self):
        self.stub.job("python-lint", f"cat <<'X'\n{VITEST}X\ncode=1")
        r = self.run_it(["python-lint"])
        self.assertEqual((r["result"], self.states(r)), ("red", [("python-lint", "run", "red")]))
        self.assertEqual(r["jobs"][0]["why"], f"exit 1: {pretest_jobs.FLAKY}")
        self.assertEqual(self.stub.ran().count("python-lint"), 2, "once more, never a third time")

    def test_a_timeout_beside_an_assertion_is_red_at_once(self):
        self.stub.job("python-lint", f"cat <<'X'\n{VITEST}AssertionError: expected 2 to be 3\nX\ncode=1")
        r = self.run_it(["python-lint"])
        self.assertEqual((r["result"], r["jobs"][0]["why"]), ("red", "exit 1"))
        self.assertEqual(self.stub.ran().count("python-lint"), 1)

    def test_a_rerun_the_budget_does_not_reach_is_skipped_never_red(self):
        self.stub.job("python-lint", once_then("seen", f"sleep 1; cat <<'X'\n{VITEST}X\ncode=1", "sleep 30"))
        r = self.run_it(["python-lint"], budget=2.5)
        self.assertEqual((r["result"], self.states(r)), ("skipped", [("python-lint", "skipped", None)]))
        self.assertEqual(r["jobs"][0]["why"], "the budget ended while it ran")

    def test_timeout_only_by_its_lines(self):
        only = pretest_jobs.timeout_only
        self.assertTrue(only(VITEST))
        self.assertTrue(only("(fail) sync > merges [5001.00ms]\n  ^ this test timed out after 5000ms.\n 1 fail\n"))
        self.assertFalse(only(VITEST.replace("1 failed | 311", "2 failed | 310")), "one timeout, two failures")
        self.assertFalse(only("error[E0425]: cannot find value\nTest timed out in 5000ms"))
        self.assertFalse(only("exit 1"))


class TheMacs(FieldCase):
    def test_a_dyld_library_not_loaded_red_is_the_macs_and_skipped(self):
        self.stub.job("records-check", f"cat <<'X'\n{DYLD}X\ncode=101")
        r = self.run_it(["records-check", "bash-lint"], parallel=1)
        self.assertEqual((r["result"], self.states(r)),
                         ("skipped", [("records-check", "skipped", None), ("bash-lint", "run", "green")]))
        self.assertTrue(r["jobs"][0]["why"].startswith(pretest_jobs.MAC), r["jobs"][0]["why"])
        self.assertIn("libabsl_die_if_null", r["why"], "the pretest line names it")
        self.assertIn("bash-lint", self.stub.ran(), "no red: the other jobs go on")

    def test_a_library_a_cars_build_misses_is_still_red(self):
        self.stub.job("records-check", "echo 'ld: library not found for -lfoo'; code=1")
        self.assertEqual(self.run_it(["records-check"])["result"], "red")


class CiEnvironment(FieldCase):
    def test_every_job_sees_the_runners_environment_unless_its_config_says_no(self):
        r = self.run_it(["python-lint", "records-check"], plain=("records-check",))
        self.assertEqual(r["result"], "green")
        ci = {j: (self.stub.dir / f"ci-{j}").read_text().strip() for j in ("python-lint", "records-check")}
        self.assertEqual(ci, {"python-lint": "true|true|0", "records-check": "||"})
        cfg = pretest.read_config(config(self.tmp / "p.toml", ["python-lint", "records-check"],
                                         plain=("records-check",)))[0]
        self.assertEqual(cfg["plain"], {"records-check"})

    def test_the_repos_config_runs_no_rust_build(self):
        """Plan 0490 step 17: records-check (five CLIs built cold in every train's new field, killed at the budget in
        every train since 2026-10-20) left the repo's config; no configured job builds Rust."""
        from pathlib import Path
        repo = Path(__file__).resolve().parents[8]
        cfg = pretest.read_config(repo / pretest.CONFIG)[0]
        self.assertIsNotNone(cfg, "the repo's .github/hal2-pretest.toml reads")
        self.assertNotIn("records-check", cfg["jobs"])
        self.assertEqual(cfg["plain"], set())
        gate = repo / "code/bash/scripts/gate/jobs"
        for job in cfg["jobs"]:
            code = "\n".join(ln for ln in (gate / f"{job}.sh").read_text().splitlines() if not ln.lstrip().startswith("#"))
            self.assertNotRegex(code, r"\bcargo\b|candidate_clis", f"{job} builds Rust")


if __name__ == "__main__":
    unittest.main()
