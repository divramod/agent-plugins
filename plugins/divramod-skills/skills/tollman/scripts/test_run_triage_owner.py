"""Hal2 plan 0556 step 1 (L195): a red test without a spec goes to the field that last changed its file, never to the
car that only touched the gate's script. Train 36's run 41256483220 replayed (fixtures/run_triage/train-36.*: the
records-check job red in its state-scratch phase on a hal2-workqueue budget test): car 05 changed
`code/bash/scripts/gate/jobs/records-check.sh`, car 48 the test's file; the verdict is car 48's (`file`). Without a
resolving file, or on a build-phase timeout, the pipeline rule keeps car 05."""

import copy
import shutil
import tempfile
import unittest

import run_triage
import run_triage_check as check
import run_triage_gather as gather
import run_triage_read as read
from test_run_triage import TRAINS, commit, context, git, recorded

BUDGET = "code/rust/libs/hal2-workqueue/tests/it/budget.rs"
GATE_SH = "code/bash/scripts/gate/jobs/records-check.sh"
TEST = "hal2-workqueue::it budget::a_history_page_of_a_20k_line_day_within_budget"
COLS = "c2-09-records-check\t[05] gate records-check\t2026-11-01T00:46:30.5000000Z "


def replay(log: str | None = None, **kw) -> dict:
    """The one verdict of train 36's run (its log, or `log` instead), keyed nowhere: the run has one red unit."""
    data, jobs, recorded_log = recorded("36")
    run = {"id": "41256483220", "url": data["url"], "sha": data["headSha"], "base": TRAINS["36"]["base"]}
    verdicts = run_triage.triage(run, jobs, recorded_log if log is None else log, context("36", **kw))["verdicts"]
    assert len(verdicts) == 1, [v["key"] for v in verdicts]
    return verdicts[0]


class Train36(unittest.TestCase):
    """The replayed run: the test's file owns the red, the gate script's car does not."""

    def test_the_test_file_s_field_owns_the_red(self):
        v = replay()
        self.assertEqual(v["key"], "triage:41256483220:records-check")
        self.assertEqual((v["kind"], v["cause"], v["owner"]), ("file", "file", "48"))
        self.assertNotEqual(v["owner"], "05")
        self.assertEqual(v["evidence"]["file"], BUDGET)
        self.assertEqual(v["evidence"]["tests"], [TEST])
        self.assertEqual(v["evidence"]["owner"]["from"]["by"], "car")
        self.assertIsNone(v["evidence"]["pipeline"])

    def test_a_live_field_by_its_worktree_trailer(self):
        v = replay(live={"05", "48"})
        self.assertEqual((v["kind"], v["owner"], v["live"]), ("file", "48", True))
        self.assertEqual(v["evidence"]["owner"]["from"]["by"], "worktree")

    def test_the_recheck_agrees_with_the_first_verdict(self):
        v = replay()
        self.assertEqual(check.recheck(v["evidence"]), ("file", "48"))
        self.assertEqual(v["recheck"], "agrees")

    def test_the_nextest_name_alone_resolves_and_stands_in_the_evidence(self):
        _, _, log = recorded("36")
        v = replay("\n".join(t for t in log.splitlines() if "panicked at" not in t))
        self.assertEqual((v["kind"], v["owner"], v["recheck"]), ("file", "48", "agrees"))
        self.assertEqual(v["evidence"]["owner"]["test"], TEST)
        self.assertTrue(any(TEST in t for t in v["evidence"]["lines"]))

    def test_the_recheck_disagrees_when_the_lines_lose_the_test(self):
        v = copy.deepcopy(replay())
        v["evidence"]["lines"] = [t for t in v["evidence"]["lines"] if "budget.rs" not in t]
        self.assertNotEqual(check.recheck(v["evidence"]), ("file", "48"))
        out = check.settle(v)
        self.assertEqual((out["kind"], out["owner"], out["recheck"]), ("unsure", None, "disagrees"))


class Pipeline(unittest.TestCase):
    """What keeps the pipeline rule: no test file in the repository, no known owner of it, a timeout."""

    def assert_pipeline_05(self, v: dict) -> None:
        self.assertEqual((v["kind"], v["cause"], v["owner"], v["recheck"]), ("pipeline", "pipeline", "05", "agrees"))
        self.assertEqual(v["evidence"]["pipeline"]["cars"], ["05"])

    def test_nothing_resolves_to_a_repository_file(self):
        self.assert_pipeline_05(replay(paths=[], owners={}))

    def test_a_resolved_file_without_a_known_commit(self):
        self.assert_pipeline_05(replay(owners={}))

    def test_a_build_phase_timeout(self):
        _, _, log = recorded("36")
        v = replay(log + "\n" + COLS + "[00:46:30] phase build: failed after 600s (exit 124)\n")
        self.assert_pipeline_05(v)
        self.assertIsNone(v["evidence"]["file"])

    def test_the_recheck_of_a_stack_step_at_the_build_limit_is_the_pipeline_s(self):
        e = {**copy.deepcopy(replay()["evidence"]), "step": "[06] gate stack-test hub-e2e", "secs": 700,
             "pipeline": {"cars": ["05"]}}
        self.assertEqual(check.recheck(e), ("pipeline", "05"))  # L137 before L195's file rule


class Candidates(unittest.TestCase):
    """The log forms of a failing test's file and the repository paths they stand for (D2: exactly one or none)."""

    def test_the_log_forms(self):
        text = ("thread 'x' panicked at libs/hal2-workqueue/tests/it/budget.rs:141:5:\n"
                "        FAIL [   2.392s] ( 14/238) hal2-workqueue::it budget::a\n"
                "        FAIL [   0.052s] (  935/ 14017) hal2-core budgets::tests::b\n"
                "#  (in test file code/bash/scripts/gate/test.bats, line 12)\n")
        f = read.facts(text.splitlines())
        self.assertEqual(f["files"], ["libs/hal2-workqueue/tests/it/budget.rs", "code/bash/scripts/gate/test.bats",
                                      "hal2-workqueue::it budget::a", "hal2-core budgets::tests::b"])
        self.assertEqual(f["tests"], ["hal2-workqueue::it budget::a", "hal2-core budgets::tests::b"])
        self.assertFalse([t for t in f["tests"] + f["files"] if t.startswith("(") or "/238" in t])

    def test_the_suffixes_of_each_form(self):
        self.assertEqual(read.candidates("hal2-workqueue::it budget::a"),
                         ["hal2-workqueue/tests/it/budget.rs", "hal2-workqueue/tests/it/budget/mod.rs"])
        self.assertEqual(read.candidates("hal2-workqueue::it a"),
                         ["hal2-workqueue/tests/it.rs", "hal2-workqueue/tests/it/main.rs"])
        self.assertEqual(read.candidates("hal2-core budgets::tests::b"),
                         ["hal2-core/src/budgets/tests.rs", "hal2-core/src/budgets/tests/mod.rs",
                          "hal2-core/src/budgets.rs", "hal2-core/src/budgets/mod.rs"])
        self.assertEqual(read.candidates("hal2-cli-git::bin/hal2-cli-git cli::c"),
                         ["hal2-cli-git/src/cli.rs", "hal2-cli-git/src/cli/mod.rs"])
        self.assertEqual(read.candidates("hal2-core a"), ["hal2-core/src/lib.rs"])
        self.assertEqual(read.candidates("code/bash/scripts/gate/test.bats"), ["code/bash/scripts/gate/test.bats"])
        self.assertEqual(read.candidates("budget"), [])

    def test_exactly_one_path_or_none(self):
        paths = ["code/rust/libs/hal2-core/src/budgets.rs", BUDGET, "code/bash/scripts/gate/test.bats"]
        self.assertEqual(run_triage.resolve_test("hal2-core budgets::tests::b", paths), paths[0])  # inline tests
        self.assertEqual(run_triage.resolve_test("hal2-workqueue::it budget::a", paths), BUDGET)
        self.assertEqual(run_triage.resolve_test("libs/hal2-workqueue/tests/it/budget.rs", paths), BUDGET)
        self.assertEqual(run_triage.resolve_test("code/bash/scripts/gate/test.bats", paths), paths[2])
        self.assertIsNone(run_triage.resolve_test("hal2-x::it y::z", paths))
        twice = [BUDGET, "vendor/hal2-workqueue/tests/it/budget.rs"]
        self.assertIsNone(run_triage.resolve_test("hal2-workqueue::it budget::a", twice))  # no guess


class GatherOwners(unittest.TestCase):
    """gather.owners against a real git repository: the newest commit of the test's file at the run's sha."""

    @classmethod
    def setUpClass(cls):
        cls.main = main = tempfile.mkdtemp()
        git(main, "init", "-q", "-b", "main")
        git(main, "config", "user.email", "t@t")
        git(main, "config", "user.name", "t")
        commit(main, BUDGET, "feat(0420|3): budgets\n\nWorktree: 31\nPlan: 0420-budgets")
        cls.before = git(main, "rev-parse", "HEAD")
        commit(main, GATE_SH, "feat(0428|2): gate\n\nWorktree: 05\nPlan: 0428-mac-vm-bash-test")
        commit(main, BUDGET, "fix(0531|16): budgets widened\n\nWorktree: 48\nPlan: 0531-no-inline-tests")
        cls.sha = git(main, "rev-parse", "HEAD")
        _, jobs, log = recorded("36")
        cls.units = read.units(jobs, log)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.main, True)

    def test_the_newest_commit_names_its_field(self):
        paths, owners = gather.owners(self.main, self.sha, self.units)
        self.assertEqual(paths, [BUDGET])
        self.assertEqual({k: owners[BUDGET][k] for k in ("sha", "worktree", "plan")},
                         {"sha": self.sha, "worktree": "48", "plan": "0531-no-inline-tests"})
        self.assertNotIn(GATE_SH, owners)

    def test_at_an_earlier_sha_the_commit_before(self):
        _, owners = gather.owners(self.main, self.before, self.units)
        self.assertEqual(owners[BUDGET]["worktree"], "31")

    def test_no_failing_test_reads_nothing(self):
        self.assertEqual(gather.owners(self.main, self.sha, [{"lines": ["error: something"]}]), ([], {}))


if __name__ == "__main__":
    unittest.main()
