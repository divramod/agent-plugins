"""Hal2 plan 0333 step 4: a car's proof (proof.py) over one temporary repository: `main` is the barn, the branch
`06` the crop, and the checkout is the field. The checks' commands are faked (`run`): the real names check runs in
test_trains.py's replay only."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import proof


class Field(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.cache = Path(tempfile.mkdtemp()) / "cache" / "proof"
        self.addCleanup(shutil.rmtree, self.cache.parents[1], True)
        self.g("init", "-q", "-b", "main")
        self.commit({"a.rs": "a\n", "README.md": "barn\n"})
        self.g("checkout", "-q", "-b", "06")
        self.calls = []
        self.answers = {}  # the check's name -> (exit, output)

    def g(self, *a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.d, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, files):
        for f, text in files.items():
            (Path(self.d) / f).parent.mkdir(parents=True, exist_ok=True)
            (Path(self.d) / f).write_text(text)
        self.g("add", "-A")
        self.g("commit", "-q", "-m", "x")
        return self.g("rev-parse", "HEAD")

    def run_(self, argv, cwd):
        """git for real; a check answers from `answers` and is counted."""
        if argv[0] == "git":
            return proof.sh(argv, cwd)
        name = "records" if argv[0] == "hal2-cli-records" else "names"
        self.calls.append(name)
        return self.answers.get(name, (0, "ok"))

    def names_script(self):
        script = Path(self.d) / proof.NAMES
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("")

    def verdict(self, head):
        return proof.verdict("-", self.d, head, "main", run=self.run_, cache=self.cache)


class Checks(Field):
    def test_which_checks_run_for_which_diff(self):
        self.assertEqual(proof.checks_for(["code/rust/a.rs"]), ["names"])
        for f in ("plans/0333-x/plan.md", ".adr/x.md", "docs/ci.md", "code/x/README.md", "docs/a.toml"):
            self.assertEqual(proof.checks_for(["a.rs", f]), ["names", "records"], f)

    def test_a_code_crop_runs_the_names_check_only_and_rides(self):
        self.names_script()
        head = self.commit({"b.rs": "b\n"})
        v = self.verdict(head)
        self.assertEqual((v["state"], v["checks"], self.calls), ("green", ["names"], ["names"]))

    def test_a_finding_in_the_crop_is_red_with_its_line_and_one_outside_it_is_not_the_cars(self):
        self.names_script()
        head = self.commit({"plans/0255-x/uat.md": "the slot's pane\n"})
        self.answers["names"] = (1, "plans/0255-x/uat.md:1: slot - use worktree\nREADME.md:1: lead - use foreman\n"
                                    "1 old words in the added lines")
        self.answers["records"] = (1, "docs/other.md: missing key `title` (spec:required-key)\nfailed: 1 problems")
        v = self.verdict(head)
        self.assertEqual((v["state"], v["lines"]), ("red", ["names: plans/0255-x/uat.md:1: slot - use worktree"]))
        self.assertEqual(v["checks"], ["names", "records"])

    def test_a_check_that_cannot_run_is_skipped_never_red(self):
        head = self.commit({"docs/x.md": "x\n"})  # no names script in this field
        self.answers["records"] = (127, "")
        v = self.verdict(head)
        self.assertEqual((v["state"], v["checks"], v["skipped"]), ("green", [], ["names", "records"]))

    def test_uncommitted_work_is_not_the_cars(self):
        self.names_script()
        head = self.commit({"docs/x.md": "x\n"})
        (Path(self.d) / "docs/x.md").write_text("x\nthe slot\n")
        self.answers["names"] = (1, "docs/x.md:2: slot - use worktree")
        v = self.verdict(head)
        self.assertEqual((v["state"], v["dropped"]), ("green", 1))
        self.assertEqual(list(self.cache.glob("*.json")), [], "a verdict that left findings out is not kept")


class Waits(Field):
    def test_a_field_not_at_its_hitched_head_waits_and_nothing_runs_or_is_kept(self):
        self.names_script()
        hitched = self.commit({"b.rs": "b\n"})
        self.commit({"c.rs": "c\n"})  # the foreman went on after the hitch
        v = self.verdict(hitched)
        self.assertEqual(v["state"], "wait")
        self.assertIn("no proof yet", v["lines"][0])
        self.assertEqual((self.calls, list(self.cache.glob("*.json"))), ([], []))

    def test_a_missing_field_waits(self):
        v = proof.verdict("-", str(Path(self.d) / "gone"), "0" * 40, "main", run=self.run_, cache=self.cache)
        self.assertEqual(v["state"], "wait")


class Cache(Field):
    def test_a_verdict_is_kept_per_field_and_head(self):
        self.names_script()
        head = self.commit({"b.rs": "b\n"})
        self.answers["names"] = (1, "b.rs:1: slot - use worktree")
        first = self.verdict(head)
        self.answers["names"] = (0, "ok")
        self.assertEqual(self.verdict(head)["state"], first["state"], "the cache answers")
        self.assertEqual(self.calls, ["names"], "the check ran once")
        self.assertTrue((self.cache.parent / "CACHEDIR.TAG").is_file())
        moved = self.commit({"b.rs": "fixed\n"})
        self.assertEqual(self.verdict(moved)["state"], "green", "a new head is proven again")
        self.assertEqual(self.calls, ["names", "names"])

    def test_old_verdicts_are_pruned(self):
        old = self.cache / "old.json"
        self.cache.mkdir(parents=True)
        old.write_text("{}")
        proof.keep(self.cache, "06", "a" * 40, {"state": "green"}, now=old.stat().st_mtime + proof.KEEP + 1)
        self.assertFalse(old.exists())
        self.assertEqual(proof.cached(self.cache, "06", "a" * 40)["state"], "green")


if __name__ == "__main__":
    unittest.main()
