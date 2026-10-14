"""Hal2 plan 0294 step 8: the yard job's survey and carry (yard.py) over test_yard.py's temporary repositories: what
skips the whole yard, and the one commit in the wagon master's field."""

import os
import unittest

import yard
from test_yard import Yard, git


class Surveying(Yard):
    def test_a_yard_on_another_branch_in_a_merge_or_ahead_is_skipped(self):
        self.write({"docs/a.md": "changed\n"})
        self.assertEqual(yard.survey(str(self.yard)), {"skipped": None, "entries": [{"xy": " M", "path": "docs/a.md"}]})
        git(self.yard, "checkout", "-q", "-b", "side")
        self.assertEqual(self.look(), {"skipped": "the yard is on side, not on main", "placed": [], "left": []})
        git(self.yard, "checkout", "-q", "--detach")
        self.assertEqual(self.look()["skipped"], "the yard is on a detached head, not on main")
        git(self.yard, "checkout", "-q", "main")
        for mark, what in (("MERGE_HEAD", "a merge"), ("rebase-merge", "a rebase"), ("CHERRY_PICK_HEAD", "a cherry-pick")):
            (self.yard / ".git" / mark).write_text("x")
            self.assertEqual(self.look()["skipped"], f"{what} is under way in the yard")
            (self.yard / ".git" / mark).unlink()
        git(self.yard, "commit", "-qam", "never pushed")
        self.write({"docs/b.md": "changed\n"})
        self.assertEqual(self.look()["skipped"], "the yard is 1 commits ahead of origin/main")
        self.assertEqual(yard.carry(str(self.yard), str(self.field), self.look()["placed"]), (None, [], ""))

    def test_a_staged_rename_is_a_deletion_and_an_addition(self):
        git(self.yard, "mv", "docs/b.md", "docs/moved.md")
        self.assertEqual(yard.survey(str(self.yard))["entries"],
                         [{"xy": "D ", "path": "docs/b.md"}, {"xy": "A ", "path": "docs/moved.md"}])
        self.assertEqual(self.sorted(), (["docs/b.md", "docs/moved.md"], {}))


class Carrying(Yard):
    def test_the_placed_files_are_one_commit_in_the_field_each_with_its_hash(self):
        self.write({"docs/a.md": "changed\n", "docs/new.md": "new\n", ".env": "A=1\n"})
        os.symlink("a.md", self.yard / "docs/link")
        (self.yard / "docs/c.md").unlink()
        (self.yard / "docs/new.md").chmod(0o755)
        before, base = self.state(), git(self.field, "rev-parse", "HEAD")
        commit, carried, why = self.carry()
        self.assertEqual((why, commit, git(self.field, "rev-parse", "HEAD~1")), ("", git(self.field, "rev-parse", "HEAD"), base))
        self.assertEqual(git(self.field, "log", "-1", "--format=%s"), "chore(yard): 4 files from the yard")
        self.assertEqual(git(self.field, "show", "--name-status", "--format=", "HEAD").split(),
                         ["M", "docs/a.md", "D", "docs/c.md", "A", "docs/link", "A", "docs/new.md"])
        self.assertEqual([c["path"] for c in carried], ["docs/a.md", "docs/c.md", "docs/link", "docs/new.md"])
        for c in carried:
            there = None if c["path"] == "docs/c.md" else git(self.field, "rev-parse", f"HEAD:{c['path']}")
            self.assertEqual((c["hash"], yard.blob(str(self.yard), c["path"])), (there, there), c["path"])
        self.assertIn("120000", git(self.field, "ls-tree", "HEAD", "docs/link"))
        self.assertIn("100755", git(self.field, "ls-tree", "HEAD", "docs/new.md"))
        self.assertEqual((self.state(), self.state(self.field)[0]), (before, ""), "the yard as it was, the field clean")

    def test_nothing_placed_is_no_commit(self):
        self.write({".env": "A=1\n", "scratch/x.md": "x"})
        base = self.state(self.field)
        self.assertEqual((self.carry(), self.state(self.field)), ((None, [], ""), base))
        self.write({"docs/a.md": "a\n"})  # touched, the same content
        self.assertEqual((self.carry(), self.state(self.field)), ((None, [], ""), base))

    def test_a_failing_hook_or_a_car_that_would_not_merge_leaves_the_field_as_it_was(self):
        self.write({"docs/a.md": "the yard's\n", "docs/new.md": "new\n"})
        (self.yard / "docs/c.md").unlink()
        base, hook = self.state(self.field), self.yard / ".git/hooks/pre-commit"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text("#!/bin/sh\necho no >&2\nexit 1\n")
        hook.chmod(0o755)
        commit, carried, why = self.carry()
        self.assertEqual((commit, carried, self.state(self.field)), (None, [], base), "hooks run, never --no-verify")
        self.assertIn("no", why)
        hook.unlink()
        car = {"field": "07", "head": self.crop({"docs/a.md": "seven's\n"})}
        placed = self.look()["placed"]  # sorted without the car: the trial merge is the last check
        commit, carried, why = yard.carry(str(self.yard), str(self.field), placed, [car])
        self.assertEqual((commit, carried, self.state(self.field)), (None, [], base))
        self.assertEqual(why, "car 07 would not merge onto the yard's commit (docs/a.md)")


if __name__ == "__main__":
    unittest.main()
