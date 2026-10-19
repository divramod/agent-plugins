"""Half-removed fields (halfway.py; hal2 plan 0377 step 5, D7, PR19, RN8): a removal killed midway is resumed by the
next run; without a journal deleted tracked files are restored only when HEAD is on origin, a folder left without its
worktree is never deleted. On the scratch farm behind fake CLIs (fake_clis.py)."""

import os
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
from fake_clis import parse
from test_farmer import git

PRUNE = Path(__file__).resolve().parent / "prune.py"


def worktree_names(main) -> list[str]:
    out = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=main, capture_output=True, text=True).stdout
    return [Path(x[9:]).name for x in out.splitlines() if x.startswith("worktree ")]


@unittest.skipIf(os.name == "nt", "kills a process group")
class Killed(fake_clis.Farm):
    def test_pr19_rn8_a_removal_killed_midway_is_resumed_by_the_next_run(self):
        path = self.add("23")
        tracked = len(subprocess.run(["git", "ls-files"], cwd=path, capture_output=True, text=True).stdout.split())
        self.feed(slow_remove=0.5)
        deleted = Path(self.env["PRUNE_FAKE_STATE"]) / "deleted"
        p = subprocess.Popen([sys.executable, str(PRUNE), "run", "--repo", str(self.main)], env=os.environ,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(lambda: p.poll() is None and os.killpg(p.pid, signal.SIGKILL))
        end = time.time() + 240
        while time.time() < end and (not deleted.exists() or len(deleted.read_text().split()) < 2):
            self.assertIsNone(p.poll(), "the run ended before its removal was cut off")
            time.sleep(0.1)
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        gone = len(deleted.read_text().split())
        self.assertTrue(path.is_dir() and "23" in worktree_names(self.main), "half-removed: still a worktree")
        self.assertLess(gone, tracked)
        self.assertEqual(list(halfway.journal(str(self.main))), ["23"], "the killed removal left its journal")

        self.feed(slow_remove=0)
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        self.assertTrue(any(x.startswith("half-removed 23: a journaled removal was cut off") for x in lines), lines)
        (step,) = parse(lines)["phase-1"]
        self.assertEqual((step[0], step[1]), ("field 23", "success"))
        self.assertTrue(step[2][0].startswith("resumed the removal of 23"), step)
        self.assertFalse(path.exists())
        self.assertNotIn("23", worktree_names(self.main))
        self.assertEqual(halfway.journal(str(self.main)), {})
        self.assertEqual(self.calls()[-1], ["worktree", "remove", "23", "--remote", "--force"])


class Unjournaled(fake_clis.Farm):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(halfway, "HALF_MIN", 3)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = self.add("23")
        for f in ("file0.txt", "file1.txt", "file2.txt", "file3.txt"):
            (self.path / f).unlink()

    def test_pr19_deleted_files_are_restored_when_head_is_on_origin_then_the_proof_removes_the_field(self):
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        steps = parse(lines)["phase-1"]
        self.assertEqual([(s[0], s[1]) for s in steps], [("field 23", "success"), ("field 23", "success")])
        self.assertTrue(steps[0][2][0].startswith("restored 4 tracked files of 23"))
        self.assertIn("removed 23", steps[1][2][-1])
        self.assertFalse(self.path.exists())

    def test_pr19_head_on_no_origin_branch_leaves_the_field_and_says_so(self):
        git(self.path, "commit", "-q", "--allow-empty", "-m", "local only")
        code, lines = self.prune()
        self.assertEqual(code, 0)
        (step,) = parse(lines)["phase-1"]
        self.assertEqual(step[1], "skipped")
        self.assertIn("HEAD on no origin branch: restore by hand", step[2][0])
        self.assertFalse((self.path / "file0.txt").exists(), "nothing restored")
        self.assertTrue(self.path.is_dir())

    def test_a_few_deleted_files_are_a_persons_edit_not_a_half_removal(self):
        with mock.patch.object(halfway, "HALF_MIN", 100):
            _, lines = self.prune()
        self.assertFalse(any(x.startswith("half-removed") for x in lines))
        self.assertEqual(parse(lines)["phase-1"], [])
        self.assertFalse((self.path / "file0.txt").exists())

    def test_the_dry_run_would_restore_and_changes_nothing(self):
        before = self.tree()
        _, lines = self.prune(dry=True)
        self.assertTrue(parse(lines)["phase-1"][0][2][0].startswith("would restore 4 tracked files of 23"))
        self.assertEqual(self.tree(), before)


class FolderLeft(fake_clis.Farm):
    def leave(self, slot: str) -> Path:
        """A field whose worktree git forgot, its folder left: `.git` gone, then `git worktree prune`."""
        path = self.add(slot)
        (path / ".git").unlink()
        git(self.main, "worktree", "prune")
        return path

    def test_without_a_journal_the_folder_is_never_deleted(self):
        path = self.leave("36")
        code, lines = self.prune()
        self.assertEqual(code, 0)
        (step,) = parse(lines)["phase-1"]
        self.assertEqual((step[0], step[1]), ("field 36", "skipped"))
        self.assertIn("no prune run began its removal: check it by hand", step[2][0])
        self.assertTrue(path.is_dir())

    def test_a_journaled_folder_is_deleted_and_its_branch_dropped(self):
        path = self.add("36")
        halfway.begin(str(self.main), {"slot": "36", "path": str(path), "head": "x", "branch": "36"}, None)
        (path / ".git").unlink()
        git(self.main, "worktree", "prune")
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        (step,) = parse(lines)["phase-1"]
        self.assertEqual(step[1], "success")
        self.assertIn("resumed the removal of 36: folder deleted", step[2][0])
        self.assertFalse(path.exists())
        self.assertFalse(subprocess.run(["git", "rev-parse", "--verify", "--quiet", "refs/heads/36"], cwd=self.main,
                                        capture_output=True).returncode == 0)
        self.assertEqual(halfway.journal(str(self.main)), {})

    def test_a_journaled_folder_whose_branch_holds_work_is_left(self):
        path = self.add("36")
        git(path, "commit", "-q", "--allow-empty", "-m", "local only")
        halfway.begin(str(self.main), {"slot": "36", "path": str(path), "head": "x", "branch": "36"}, None)
        (path / ".git").unlink()
        git(self.main, "worktree", "prune")
        _, lines = self.prune()
        (step,) = parse(lines)["phase-1"]
        self.assertEqual(step[1], "skipped")
        self.assertIn("branch 36 holds commits not on origin/main", step[2][0])
        self.assertTrue(path.is_dir())

    def test_a_journal_that_deleted_nothing_is_dropped_and_the_proof_decides(self):
        path = self.add("23")
        halfway.begin(str(self.main), {"slot": "23", "path": str(path), "head": "x", "branch": "23"}, None)
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        steps = parse(lines)["phase-1"]
        self.assertIn("deleted nothing yet", steps[0][2][0])
        self.assertIn("removed 23", steps[1][2][-1])
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
