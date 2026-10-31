"""Hal2 plan 0490 step 23 (D24): a field that committed on after its hitch is proven on its hitched sha in the farm's
kept scratch worktree (proof_scratch.py), moved and cleaned per proof; the field's checkout is never changed. The
repository and the scratch root are the test's temp folders (test_proof.Field); the checks are faked, git runs for
real."""

import fcntl
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import proof
import proof_scratch
from test_proof import Field


class Moved(Field):
    def setUp(self):
        super().setUp()
        self.names_script()
        self.root = self.cache.parent / "scratch"
        self.seen = []  # the folders the names check ran in

    def run_(self, argv, cwd):
        """The names check reads the crop's file where it runs: red while it holds the old word."""
        if argv[0] in ("git", "gh", "hal2-cli-records"):
            return super().run_(argv, cwd)
        self.calls.append("names")
        self.seen.append(cwd)
        text = (Path(cwd) / "docs/x.md").read_text() if (Path(cwd) / "docs/x.md").is_file() else ""
        return (1, "docs/x.md:1: slot - use worktree") if "slot" in text else (0, "ok")

    def worktrees(self):
        return [ln for ln in self.g("worktree", "list", "--porcelain").splitlines() if ln.startswith("worktree ")]

    def kept(self):
        return self.root / proof_scratch.NAME

    def assert_kept(self, head):
        self.assertTrue(proof_scratch.is_worktree(self.kept()), "the scratch is kept")
        self.assertEqual(len(self.worktrees()), 2, "the field and the kept scratch")
        self.assertEqual(subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.kept(), capture_output=True,
                                        text=True).stdout.strip(), head)

    def assert_gone(self):
        self.assertFalse(self.kept().exists(), "no scratch is left")
        self.assertEqual(len(self.worktrees()), 1, "only the field's own worktree is left")

    def counting(self):
        """GIT recording each scratch git call's verb."""
        verbs = []

        def run(argv, **kw):
            verbs.append(next(a for a in argv[3:] if not a.startswith("-")))
            return proof_scratch.bounded.run(argv, **kw)
        return verbs, run

    def test_a_field_one_commit_past_its_hitched_head_rides_green_on_the_hitched_sha(self):
        hitched = self.commit({"b.rs": "b\n"})
        now = self.commit({"c.rs": "c\n"})  # the foreman went on after the hitch
        v = self.verdict(hitched)
        self.assertEqual((v["state"], v["checks"], self.calls), ("green", ["names"], ["names"]))
        self.assertEqual(self.seen, [str(self.kept())])
        self.assertEqual(self.g("rev-parse", "HEAD"), now, "the field's checkout is not changed")
        self.assert_kept(hitched)
        self.assertEqual(proof.cached(self.cache, Path(self.d).name, hitched)["state"], "green", "kept per field:head")

    def test_the_kept_scratch_is_reused_moved_and_cleaned(self):
        first = self.commit({"b.rs": "b\n"})
        self.commit({"c.rs": "c\n"})
        self.verdict(first)
        (self.kept() / "junk.txt").write_text("left by a check\n")
        (self.kept() / "b.rs").write_text("changed by a check\n")
        second = self.commit({"d.rs": "d\n"})
        self.commit({"e.rs": "e\n"})
        verbs, run = self.counting()
        with mock.patch.object(proof_scratch, "GIT", run):
            self.assertEqual(self.verdict(second)["state"], "green")
        self.assertEqual(verbs, ["checkout", "clean"], "no second add")
        self.assert_kept(second)
        self.assertFalse((self.kept() / "junk.txt").exists())
        self.assertEqual((self.kept() / "b.rs").read_text(), "b\n")

    def test_the_hitched_sha_is_red_for_a_finding_the_newer_commit_fixed(self):
        hitched = self.commit({"docs/x.md": "the slot\n"})
        self.commit({"docs/x.md": "the worktree\n"})
        v = self.verdict(hitched)
        self.assertEqual((v["state"], v["lines"]), ("red", ["names: docs/x.md:1: slot - use worktree"]))

    def test_uncommitted_work_in_the_field_is_none_on_the_hitched_sha(self):
        hitched = self.commit({"docs/x.md": "the slot\n"})
        self.commit({"c.rs": "c\n"})
        (Path(self.d) / "docs/x.md").write_text("the worktree\n")  # dirty in the field: not the hitched sha's
        v = self.verdict(hitched)
        self.assertEqual((v["state"], v["dropped"]), ("red", 0))

    def test_a_failing_worktree_add_waits_and_nothing_runs_or_is_kept(self):
        self.commit({"c.rs": "c\n"})
        v = self.verdict("f" * 40)  # no such commit: git worktree add fails
        self.assertEqual(v["state"], "wait")
        self.assertIn("scratch worktree could not be had: git worktree add failed", v["lines"][0])
        self.assertEqual((self.calls, list(self.cache.glob("*.json"))), ([], []))
        self.assert_gone()

    def test_a_timed_out_worktree_add_waits(self):
        hitched = self.commit({"b.rs": "b\n"})
        self.commit({"c.rs": "c\n"})

        def slow(argv, **kw):
            if "add" in argv:
                raise subprocess.TimeoutExpired(argv, kw["timeout"])
            return proof_scratch.bounded.run(argv, **kw)

        with mock.patch.object(proof_scratch, "GIT", slow):
            v = self.verdict(hitched)
        self.assertEqual(v["state"], "wait")
        self.assertIn(f"timed out after {proof_scratch.ADD} s", v["lines"][0])
        self.assert_gone()

    def test_a_failing_checkout_drops_the_scratch_and_the_next_proof_makes_it_again(self):
        hitched = self.commit({"b.rs": "b\n"})
        self.commit({"c.rs": "c\n"})
        self.verdict(hitched)
        v = proof_scratch.prove(self.d, "e" * 40, "main", self.root, lambda *a: {"state": "green"})
        self.assertEqual(v["state"], "wait")
        self.assertIn("git checkout failed", v["lines"][0])
        self.assert_gone()
        self.cache_clear()
        self.assertEqual(self.verdict(hitched)["state"], "green")
        self.assert_kept(hitched)

    def test_a_broken_or_prunable_scratch_is_dropped_and_made_again(self):
        hitched = self.commit({"b.rs": "b\n"})
        self.commit({"c.rs": "c\n"})
        self.kept().mkdir(parents=True)
        (self.kept() / "junk").write_text("not a worktree")
        self.assertEqual(self.verdict(hitched)["state"], "green")
        self.assert_kept(hitched)
        admin = Path(self.g("rev-parse", "--git-common-dir"))
        shutil.rmtree((Path(self.d) / admin / "worktrees" / proof_scratch.NAME))  # prunable: its admin folder gone
        self.cache_clear()
        self.assertEqual(self.verdict(hitched)["state"], "green")
        self.assert_kept(hitched)

    def test_a_second_proof_while_one_runs_waits(self):
        hitched = self.commit({"b.rs": "b\n"})
        self.commit({"c.rs": "c\n"})
        self.root.mkdir(parents=True)
        with (self.root / proof_scratch.LOCK).open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            v = self.verdict(hitched)
        self.assertEqual((v["state"], self.calls), ("wait", []))
        self.assertIn("another proof is using it", v["lines"][0])

    def test_a_field_at_its_hitched_head_runs_no_scratch(self):
        head = self.commit({"b.rs": "b\n"})
        with mock.patch.object(proof_scratch, "GIT", side_effect=AssertionError("no scratch")) as git:
            v = self.verdict(head)
        self.assertEqual((v["state"], git.call_count, self.root.exists()), ("green", 0, False))
        self.assertEqual(self.seen, [self.d])

    def test_drop_never_removes_a_path_outside_the_scratch_root_or_the_root(self):
        other = Path(self.d) / "a.rs"
        proof_scratch.drop(self.d, other, self.root)
        self.assertTrue(other.is_file())
        self.root.mkdir(parents=True)
        proof_scratch.drop(self.d, self.root, self.root)
        self.assertTrue(self.root.is_dir())

    def cache_clear(self):
        for f in self.cache.glob("*.json"):
            f.unlink()


if __name__ == "__main__":
    unittest.main()
