"""Hal2 plan 0789 D2: a yard ahead of the barn (the steward committed everything and pulled the barn in with a merge)
rides with its HEAD as a merge in the carrier, before its uncommitted files; yard.settle fast-forwards it after the
landing. Over test_yard.py's temporary repositories: never a real checkout."""

from __future__ import annotations

import subprocess
import unittest
from unittest import mock

import train_fold
import yard
import yard_head
from test_yard import SECRET, Yard, git


class Ahead(Yard):
    def steward(self, files, message="steward: everything"):
        """The steward's `git add -A && git commit`: the yard's new HEAD."""
        self.write(files)
        git(self.yard, "add", "-A")
        git(self.yard, "commit", "-qm", message)
        return git(self.yard, "rev-parse", "HEAD")

    def barn_moves(self, files):
        """Another train lands meanwhile: the barn has a commit the yard lacks."""
        self.write(files, self.field)
        git(self.field, "add", ".")
        git(self.field, "commit", "-qm", "landed meanwhile")
        self.land()
        git(self.yard, "fetch", "-q", "origin")

    def ride(self, **kw):
        """look, yard_head.merge and carry in the tollman's field, as engine_yard.load_yard does."""
        seen = self.look(**kw)
        self.assertIsNone(seen["skipped"])
        merged, why = yard_head.merge(str(self.field), str(self.yard), seen["head"])
        self.assertEqual(why, "")
        commit, carried, why = yard.carry(str(self.yard), str(self.field), seen["placed"])
        self.assertEqual(why, "")
        return seen, merged, commit, carried

    def contains(self, cwd, older, newer):
        return subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], cwd=cwd).returncode == 0

    def test_a_yard_ahead_after_its_pull_merge_rides_and_is_fast_forwarded_after_the_landing(self):
        self.steward({"docs/a.md": "the steward's\n", "docs/new.md": "new\n"})
        self.barn_moves({"docs/b.md": "the barn's\n"})
        git(self.yard, "pull", "-q", "--no-rebase", "--no-edit", "origin", "main")  # the steward's merge
        head = git(self.yard, "rev-parse", "HEAD")
        self.write({"docs/c.md": "uncommitted on top\n"})
        before = self.state()
        seen, merged, commit, carried = self.ride()
        self.assertEqual((seen["head"], seen["paths"], [e["path"] for e in seen["placed"]]),
                         (head, ["docs/a.md", "docs/new.md"], ["docs/c.md"]))
        self.assertEqual((git(self.field, "rev-parse", "HEAD~1"), git(self.field, "rev-parse", f"{merged}^2")),
                         (merged, head), "the yard's HEAD merged first, its files on top")
        self.assertEqual(git(self.field, "log", "-1", "--format=%s", merged), f"chore(yard): the yard's commits up to {head[:10]}")
        self.assertEqual(git(self.field, "show", "HEAD:docs/a.md"), "the steward's")
        self.assertEqual(self.state(), before, "the yard as it was before the landing")
        self.land()
        done = yard.settle(str(self.yard), carried, "origin/main", head)
        self.assertEqual(done, {"dropped": ["docs/c.md"], "kept": [], "pulled": True, "why": ""})
        self.assertEqual(self.state(), ("", git(self.yard, "rev-parse", "origin/main")), "fast-forwarded, clean")
        self.assertTrue(self.contains(self.yard, head, "HEAD"), "the yard's commits never rewritten")

    def test_a_head_alone_rides_and_settles_with_no_file(self):
        head = self.steward({"docs/a.md": "the steward's\n"})
        seen, merged, commit, carried = self.ride()
        self.assertEqual((seen["placed"], commit, carried, git(self.field, "rev-parse", "HEAD")), ([], None, [], merged))
        self.land()
        self.assertEqual(yard.settle(str(self.yard), [], "origin/main", head)["pulled"], True)
        self.assertEqual(self.state(), ("", git(self.yard, "rev-parse", "origin/main")))
        self.assertEqual(yard.settle(str(self.yard), [], "origin/main")["pulled"], False, "no head, no file: untouched")

    def test_a_commit_with_a_refused_path_keeps_the_yard_out_and_rewrites_nothing(self):
        head = self.steward({".env.local": "A=1\n", "scratch/notes.md": "x\n", "docs/fine.md": "fine\n"})
        self.write({"docs/b.md": "uncommitted\n"})
        before = self.state()
        seen = self.look()
        self.assertEqual((seen["placed"], seen["left"], seen.get("head")), ([], [], None))
        self.assertEqual(seen["skipped"], f"the yard's commits up to {head[:10]} change 2 paths that may not ride: "
                                          f".env.local ({SECRET}); scratch/ (`scratch` is no entry of the root allowlist ("
                                          ".adr/repo-root-allowlist.md)); the commits are never rewritten")
        self.assertEqual((self.state(), git(self.field, "status", "--porcelain")), (before, ""))
        git(self.yard, "rm", "-q", "--cached", ".env.local")
        git(self.yard, "rm", "-rq", "scratch")
        git(self.yard, "commit", "-qm", "steward: out again")  # the net change no longer holds them
        self.assertEqual(self.look()["paths"], ["docs/fine.md"])

    def test_a_large_file_or_a_submodule_in_a_commit_is_refused(self):
        self.steward({"docs/big.bin": "12345"})
        with mock.patch.object(yard, "MAX", 4):
            self.assertIn("docs/big.bin (larger than 5 MB (0.0 MB))", self.look()["skipped"])

    def test_a_yard_not_based_on_the_barn_rides_on_a_clean_merge_else_it_is_said(self):
        head = self.steward({"docs/a.md": "the steward's\n"})
        self.barn_moves({"docs/b.md": "the barn's\n"})
        self.assertFalse(self.contains(self.yard, "origin/main", head))
        seen, merged, _, _ = self.ride()
        self.assertTrue(self.contains(self.field, head, "HEAD"))
        git(self.field, "reset", "-q", "--hard", "origin/main")
        self.barn_moves({"docs/a.md": "the barn's\n"})
        self.assertEqual(self.look()["skipped"], f"the yard's commits up to {head[:10]} (not based on origin/main) "
                                                 "do not merge onto the train: it conflicts (docs/a.md)")

    def test_an_unhitched_head_stays_out_until_it_changes(self):
        head = self.steward({"docs/a.md": "the steward's\n"})
        self.assertIn("were unhitched from a red train", self.look(past={"refused_head": head})["skipped"])
        new = self.steward({"docs/a.md": "mended\n"}, "steward: mended")
        self.assertEqual(self.look(past={"refused_head": head})["head"], new)

    def test_the_train_state_keeps_an_unhitched_head_out(self):
        rows = [{"kind": "yard", "files": [{"path": "docs/c.md", "hash": "h1"}], "head": "y1", "paths": ["docs/a.md"]},
                {"kind": "unhitched", "slot": "yard", "head": "y1",
                 "files": [{"path": "docs/c.md", "hash": "h1"}, {"path": "docs/a.md", "head": "y1"}]}]
        self.assertEqual(train_fold.yard_past(rows), {"carried": {"docs/c.md": ["h1"]}, "refused": {"docs/c.md": "h1"},
                                                      "refused_head": "y1"}, "a commit's path is no refused file")

    def test_a_field_that_shares_no_objects_fetches_the_head(self):
        head = self.steward({"docs/a.md": "the steward's\n"})
        clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", str(self.tmp / "hal2.git"), str(clone))
        for key, value in (("user.email", "t@t"), ("user.name", "t")):
            git(clone, "config", key, value)
        merged, why = yard_head.merge(str(clone), str(self.yard), head)
        self.assertEqual((why, git(clone, "rev-parse", f"{merged}^2")), ("", head))


if __name__ == "__main__":
    unittest.main()
