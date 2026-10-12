"""cleanup.py lists a worktree's git-ignored build artifacts and deletes only those."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "cleanup.py"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(os.path.realpath(self.tmp.name))
        self.write(".gitignore", "target/\nnode_modules/\ndist/\n.secrets/\nnotes.txt\n"
                                 "code/swift/libs/Hal2Core/Frameworks/\n")
        self.write("code/rust/src/lib.rs", "")
        self.write("dist/keep.txt", "tracked in an ignored folder\n")
        subprocess.run(["git", "init", "-q"], cwd=self.repo, env=ENV, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.repo, env=ENV, check=True)
        subprocess.run(["git", "add", "-f", "dist/keep.txt"], cwd=self.repo, env=ENV, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=self.repo, env=ENV, check=True)
        self.write("code/rust/target/debug/big", "x" * 5000)
        self.write("code/swift/libs/Hal2Core/Frameworks/Hal2Rust.xcframework/lib", "x")
        self.write("web/node_modules/pkg/index.js", "x")
        self.write("dist/out.js", "x")
        self.write(".secrets/00/TOKEN", "secret")
        self.write("notes.txt", "mine")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def run_(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.repo / "code", env=ENV,
                              text=True, capture_output=True)

    def listing(self, *args):
        r = self.run_("list", "--json", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return {a["path"]: a for a in json.loads(r.stdout)["artifacts"]}

    def test_generic_rules_without_list(self):
        rows = self.listing()
        self.assertEqual(rows["code/rust/target"]["kind"], "artifact")
        self.assertTrue(rows["code/rust/target"]["selected"])
        self.assertEqual(rows["web/node_modules"]["kind"], "kept")
        self.assertFalse(rows["web/node_modules"]["selected"])
        self.assertEqual(rows["code/swift/libs/Hal2Core/Frameworks"]["kind"], "unknown")
        self.assertEqual(rows["notes.txt"]["kind"], "unknown")
        self.assertFalse(rows["notes.txt"]["selected"])
        self.assertNotIn(".secrets", rows)

    def test_list_file_drives_it(self):
        self.write(".hal/cleanup", "# what goes\ncode/rust/target   # cargo build\n"
                                   "code/swift/libs/*/Frameworks   # build-core\n"
                                   "**/node_modules\n!web/node_modules   # bun install\n")
        rows = self.listing()
        self.assertEqual(rows["code/rust/target"]["rebuild"], "cargo build")
        self.assertTrue(rows["code/swift/libs/Hal2Core/Frameworks"]["selected"])
        self.assertEqual(rows["web/node_modules"]["kind"], "kept")
        self.assertEqual(rows["web/node_modules"]["rebuild"], "bun install")
        self.assertEqual(rows["notes.txt"]["kind"], "unknown")
        self.run_("delete")
        self.assertFalse((self.repo / "code/swift/libs/Hal2Core/Frameworks").exists())
        self.assertTrue((self.repo / "web/node_modules").exists())
        self.assertTrue((self.repo / "notes.txt").exists())

    def test_globs(self):
        spec = importlib.util.spec_from_file_location("cleanup", SCRIPT)
        c = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(c)
        self.assertTrue(c.matches("code/*/build", "code/ios/build"))
        self.assertFalse(c.matches("code/*/build", "code/a/b/build"))
        self.assertTrue(c.matches("code/**/build", "code/build"))
        self.assertTrue(c.matches("code/**/build", "code/a/b/build"))
        self.assertFalse(c.matches("code/rust/target", "code/rust/target/debug"))

    def test_dry_run_deletes_nothing(self):
        r = self.run_("delete", "--dry-run")
        self.assertIn("would delete", r.stdout)
        self.assertTrue((self.repo / "code/rust/target").exists())

    def test_delete_selected_keeps_deps_unknown_and_tracked(self):
        r = self.run_("delete")
        self.assertFalse((self.repo / "code/rust/target").exists())
        self.assertTrue((self.repo / "code/swift/libs/Hal2Core/Frameworks").exists())
        self.assertTrue((self.repo / "web/node_modules").exists())
        self.assertTrue((self.repo / "notes.txt").exists())
        self.assertTrue((self.repo / ".secrets/00/TOKEN").exists())
        # dist holds a tracked file, so git lists (and cleanup deletes) only its ignored content.
        self.assertFalse((self.repo / "dist/out.js").exists(), r.stdout)
        self.assertTrue((self.repo / "dist/keep.txt").exists(), r.stdout)

    def test_delete_refuses_unsafe_paths(self):
        for rel, why in (("code/rust/src", "holds tracked files"), ("web", "not git-ignored"), ("dist", "holds tracked files"), (".secrets", "protected"),
                         ("../..", "outside the worktree"), ("nope", "does not exist")):
            r = self.run_("delete", rel)
            self.assertEqual(r.returncode, 1)
            self.assertIn(why, r.stdout)
        self.assertTrue((self.repo / "code/rust/src/lib.rs").exists())

    def test_delete_named_path_is_worktree_relative(self):
        r = self.run_("delete", "web/node_modules")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse((self.repo / "web/node_modules").exists())

    def test_another_worktree_by_name_or_path(self):
        others = tempfile.TemporaryDirectory()
        self.addCleanup(others.cleanup)
        wt = Path(os.path.realpath(others.name)) / "03"
        subprocess.run(["git", "worktree", "add", "-q", "-b", "03", str(wt)], cwd=self.repo, env=ENV, check=True)
        (wt / "code/rust/target").mkdir(parents=True)
        (wt / "code/rust/target/big").write_text("x")
        r = self.run_("delete", "--worktree", "03")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((wt / "code/rust/target").exists())
        self.assertTrue((self.repo / "code/rust/target").exists())
        r = self.run_("list", "--worktree", str(self.repo), "--json")
        self.assertEqual(json.loads(r.stdout)["worktree"], str(self.repo))
        r = self.run_("busy", "--worktree", "07")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no worktree named 07", r.stderr)


if __name__ == "__main__":
    unittest.main()
