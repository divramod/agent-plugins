"""git_seed: the tree grown once and shared across processes, the hang guard, the child reaper; in a scratch root,
nothing left behind (tests-leave-nothing)."""
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import git_seed

HERE = Path(__file__).resolve().parent

CHILD = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import git_seed

tmp = Path(sys.argv[2])
built = []


def build():
    built.append(1)
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp)], check=True)


git_seed.grow(tmp, "child", build)
print("built" if built else "copied", flush=True)
if len(sys.argv) > 3:
    sys.stdin.readline()  # hold the root until the test says go
'''


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


class Seed(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, True)
        self.root = self.scratch / "seed-root"
        env = mock.patch.dict(os.environ, {"HAL_GIT_SEED_ROOT": str(self.root)})
        env.start()
        state = mock.patch.dict(git_seed._STATE, clear=True)
        state.start()
        self.addCleanup(state.stop)
        self.addCleanup(env.stop)
        self.addCleanup(git_seed._leave)  # runs first: the root of this test goes before the patches end
        self.builds = []

    def build_into(self, tmp):
        def build():
            self.builds.append(tmp)
            origin, work = tmp / "o.git", tmp / "w"
            git(tmp, "init", "-q", "--bare", "-b", "main", str(origin))
            git(tmp, "clone", "-q", str(origin), str(work))
            (work / "a.txt").write_text("a\n")
            git(work, "add", ".")
            git(work, "commit", "-qm", "init")
            git(work, "push", "-q", "origin", "main")
            git(work, "worktree", "add", "-q", "-b", "f", str(tmp / "f"))
        return build

    def grow(self, name="t", key="k"):
        tmp = self.scratch / name
        tmp.mkdir()
        git_seed.grow(tmp, key, self.build_into(tmp))
        return tmp

    def test_the_tree_is_grown_once_and_copied_with_its_paths_rewritten(self):
        first, second = self.grow("one"), self.grow("two")
        self.assertEqual(self.builds, [first], "built once, for the first")
        self.assertEqual(git(second / "f", "log", "--format=%s"), "init")
        self.assertEqual(git(second / "w", "remote", "get-url", "origin"), str(second / "o.git"))
        self.assertEqual(git(second / "w", "worktree", "list", "--porcelain").splitlines()[0], f"worktree {second / 'w'}")
        self.assertEqual(git(second / "f", "status", "--porcelain"), "")
        self.assertTrue((second / "o.git" / "hooks").is_dir(), "git found its templates (the sample hooks)")
        (second / "w" / "b.txt").write_text("b\n")  # the copy is the test's own
        self.assertFalse((first / "w" / "b.txt").exists())

    def test_another_key_or_another_fixture_is_another_seed(self):
        self.grow("one", "k")
        self.grow("two", "other")
        self.assertEqual(len(self.builds), 2)
        files = []
        for n, text in enumerate(("X = 1\n\ndef b():\n    pass\n", "X = 2\n\ndef b():\n    pass\n")):
            path = self.scratch / f"fix{n}.py"
            path.write_text(text)
            spec = importlib.util.spec_from_file_location(f"fix{n}", path)
            files.append(importlib.util.module_from_spec(spec))
            spec.loader.exec_module(files[-1])
        self.assertNotEqual(git_seed._digest("k", files[0].b), git_seed._digest("k", files[1].b))

    def child(self, tmp, hold=False):
        script = self.scratch / "child.py"
        script.write_text(CHILD)
        argv = [sys.executable, str(script), str(HERE), str(tmp), *(["hold"] if hold else [])]
        env = {**os.environ, "HAL_GIT_SEED_ROOT": str(self.root)}
        return git_seed.spawn(self, argv, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def test_a_second_process_copies_what_the_first_grew_and_the_last_one_out_leaves_nothing(self):
        (self.scratch / "a").mkdir()
        (self.scratch / "b").mkdir()
        first = self.child(self.scratch / "a", hold=True)
        self.assertEqual(first.stdout.readline().strip(), "built")
        self.assertTrue(self.root.is_dir())
        second = self.child(self.scratch / "b")
        self.assertEqual(second.stdout.readline().strip(), "copied")
        self.assertEqual(second.wait(timeout=30), 0)
        self.assertTrue(self.root.is_dir(), "the first process still uses the seed")
        self.assertEqual(git(self.scratch / "b", "symbolic-ref", "--short", "HEAD"), "main")
        first.stdin.write("\n")
        first.stdin.flush()
        self.assertEqual(first.wait(timeout=30), 0)
        self.assertFalse(self.root.exists(), "the last process out removed the seeds and their locks")

    def test_the_process_that_grew_alone_leaves_nothing_behind(self):
        (self.scratch / "a").mkdir()
        proc = self.child(self.scratch / "a")
        self.assertEqual(proc.stdout.readline().strip(), "built")
        self.assertEqual(proc.wait(timeout=30), 0)
        self.assertFalse(self.root.exists())

    def test_a_killed_process_drops_its_hold_and_the_next_one_clears_the_root(self):
        (self.scratch / "a").mkdir()
        proc = self.child(self.scratch / "a", hold=True)
        self.assertEqual(proc.stdout.readline().strip(), "built")
        os.killpg(proc.pid, signal.SIGKILL)  # no atexit: the root stays, its lock is free
        proc.wait(timeout=30)
        self.assertTrue(self.root.is_dir())
        self.grow("mine")
        git_seed._leave()
        self.assertFalse(self.root.exists())

    def test_the_last_one_out_moves_the_root_away_before_a_file_of_it_goes(self):
        self.grow("mine")
        (self.root.parent / f"{self.root.name}.gone-1").mkdir()  # left by a leaver killed while deleting
        removed = []

        def rmtree(path, *args):
            self.assertFalse(self.root.exists(), "a joiner never sees a half-removed root")
            removed.append(Path(path).name)
            real(path, *args)

        real = shutil.rmtree
        with mock.patch.object(git_seed.shutil, "rmtree", rmtree):
            git_seed._leave()
        self.assertEqual(sorted(removed), sorted([f"{self.root.name}.gone-1", f"{self.root.name}.gone-{os.getpid()}"]))
        self.assertEqual([p.name for p in self.scratch.iterdir() if p.name.startswith(self.root.name)], [])

    def test_a_real_git_goes_first_on_the_path_only_where_the_stub_is(self):
        path = os.environ["PATH"]
        self.root.mkdir()
        with mock.patch.object(git_seed.sys, "platform", "linux"):
            git_seed.fast_git(self.root)
        self.assertEqual(os.environ["PATH"], path, "off macOS nothing changes")
        fake = self.scratch / "real-git"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        with mock.patch.object(git_seed, "_real_git", return_value=str(fake)):
            git_seed.fast_git(self.root)
            git_seed.fast_git(self.root)
        link = Path(os.environ["PATH"].split(os.pathsep)[0])
        self.assertEqual(link.parent, self.root)
        self.assertEqual(os.environ["PATH"], os.pathsep.join([str(link), path]), "once, first")
        self.assertEqual((link / "git").read_text(), f'#!/bin/sh\nexec "{fake}" "$@"\n')
        self.assertTrue(os.access(link / "git", os.X_OK))
        with mock.patch.object(git_seed.sys, "platform", "darwin"), mock.patch.object(
                git_seed.shutil, "which", return_value="/opt/homebrew/bin/git"):
            self.assertIsNone(git_seed._real_git(), "a git of another place first: left alone")

    def test_the_hang_guard_fails_the_test_and_puts_the_old_handler_back(self):
        old = signal.getsignal(signal.SIGALRM)
        probe = unittest.TestCase("run")
        git_seed.guard(probe, 0.05)
        with self.assertRaises(TimeoutError):
            time.sleep(10)  # cut short by the alarm
        probe.doCleanups()
        self.assertIs(signal.getsignal(signal.SIGALRM), old)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_a_spawned_group_is_killed_with_its_children(self):
        proc = git_seed.spawn(self, ["sh", "-c", "sleep 60 & echo $!; wait"], stdout=subprocess.PIPE, text=True)
        grandchild = int(proc.stdout.readline())
        git_seed.reap(proc)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
        self.fail("the grandchild outlived its group")


if __name__ == "__main__":
    unittest.main()
