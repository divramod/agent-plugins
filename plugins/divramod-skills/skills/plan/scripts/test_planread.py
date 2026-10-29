"""planread.py (hal2 plan 0409 step 9): the files home reads `plans/<slug>` and starts no process; a store home renders
the plan once outside the tree, never applies it, and its sync trigger runs from a shell."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import planhome
import planread
from store_testkit import DEBUG, StoreFarm

HERE = Path(__file__).resolve().parent


class FilesHome(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="planread-")) / "repo"
        self.addCleanup(shutil.rmtree, self.tmp.parent, True)
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        planread._KIND.clear()

    def test_a_checkout_without_a_farm_reads_its_plans_folder_with_no_process(self):
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("no process")):
            self.assertEqual(planread.plan_dir(self.tmp, "0001-a"), self.tmp / "plans" / "0001-a")
            self.assertFalse(planread.is_store(self.tmp))
            self.assertIsNone(planread.sync(self.tmp, "landing"))
            with planread.registered(self.tmp):
                self.assertEqual(planhome.plans_dir(self.tmp), self.tmp / "plans")

    def test_the_farm_id_comes_from_the_config_file_also_in_a_worktree(self):
        subprocess.run(["git", "-C", str(self.tmp), "config", "hal.farm", "f-1"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                        "--allow-empty", "-m", "i"], check=True)
        field = self.tmp.parent / "07"
        subprocess.run(["git", "-C", str(self.tmp), "worktree", "add", "-q", str(field)], check=True)
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("no process")):
            self.assertEqual(planread.farm_id(self.tmp), "f-1")
            self.assertEqual(planread.farm_id(field), "f-1")

    def test_a_farm_in_the_files_home_asks_once_and_reads_the_files(self):
        subprocess.run(["git", "-C", str(self.tmp), "config", "hal.farm", "f-2"], check=True)
        planhome._HOMES.clear()
        with mock.patch.object(planhome, "run", return_value={"home": "files", "edit": None}) as run:
            self.assertEqual(planread.plan_dir(self.tmp, "0001-a"), self.tmp / "plans" / "0001-a")
            self.assertEqual(planread.plan_dir(self.tmp, "0002-b"), self.tmp / "plans" / "0002-b")
        self.assertEqual(run.call_count, 1)

    def test_the_shell_trigger_prints_nothing_in_the_files_home(self):
        done = subprocess.run([sys.executable, str(HERE / "planread.py"), "sync", "landing", "--root", str(self.tmp)],
                              capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout), (0, ""))


@unittest.skipUnless(DEBUG, "no hal2-cli-plans with the store home (cargo build -p hal2-cli-plans)")
class StoreHome(StoreFarm, unittest.TestCase):
    def test_a_plan_is_read_from_a_copy_outside_the_tree(self):
        self.cli("new", "Read me", "--no-current")
        folder = planread.plan_dir(self.repo, "0001-read-me")
        self.assertFalse(folder.is_relative_to(self.repo))
        self.assertTrue((folder / "plan.md").is_file())
        (folder / "plan.md").write_text("changed by a reader\n")  # a reader's copy: never applied
        planread._close()
        self.assertEqual(self.cli("show", "1")["title"], "Read me")
        self.assertEqual(planread.plan_dir(self.repo, "0009-none"), self.repo / "plans" / "0009-none")
        self.assert_clean()

    def test_the_shell_trigger_answers_in_the_store_home(self):
        out = self.run_ok(sys.executable, str(HERE / "planread.py"), "sync", "landing", "--root", str(self.repo))
        self.assertTrue(out.startswith("plan store sync (landing): "), out)


if __name__ == "__main__":
    unittest.main()
