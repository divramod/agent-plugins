"""cleanup.py lists a worktree's git-ignored build artifacts and deletes only those.

Every test runs twice (plan 0284, D22): with HAL_CLEANUP_CLI="" (the Python rule) and with a fake `hal2-cli-git`
on PATH that knows `worktree cleanup`, records its arguments and runs the same Python behind it, so the
arguments must arrive unchanged and its exit code is the skill's.
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent / "cleanup.py"
CASES = "code/rust/libs/hal2-git/tests/fixtures/cleanup/cases.json"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
ENV = {**os.environ, **GIT_ENV}
FAKE_USAGE = "usage: hal2-cli-git worktree cleanup list [--json] [--worktree NAME|PATH]"
# The fake is a shell script that answers the --help probe itself (no interpreter start) and hands every other
# call to fake.py beside it, which logs the arguments and runs cleanup.py's Python in its own process (runpy).
FAKE = """#!/bin/sh
if [ "$#" -ge 3 ] && [ "$1" = worktree ] && [ "$2" = cleanup ] && [ "$3" = --help ]; then
    printf '%s\\n' '{usage}'
    exit {help_code}
fi
exec {python!r} -S "$(dirname "$0")/fake.py" "$@"
"""
FAKE_PY = """import json, os, runpy, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if "FAKE_CODE" in os.environ:
    print("fake says hi")
    sys.exit(int(os.environ["FAKE_CODE"]))
os.environ["HAL_CLEANUP_CLI"] = ""
sys.path.insert(0, {scripts!r})
sys.argv = [{script!r}, *args[2:]]
runpy.run_path({script!r}, run_name="__main__")
"""


def fake_cli(folder: Path, usage=FAKE_USAGE, help_code=0) -> Path:
    """A `hal2-cli-git` in folder: it answers --help with usage and exit help_code, else logs and runs cleanup.py."""
    assert "'" not in usage
    path = folder / "hal2-cli-git"
    path.write_text(FAKE.format(python=sys.executable, usage=usage, help_code=help_code))
    path.chmod(0o755)
    (folder / "fake.py").write_text(FAKE_PY.format(scripts=str(SCRIPT.parent), script=str(SCRIPT)))
    return path


def in_process(cwd, args, env):
    """cleanup.py run as `python3 cleanup.py <args>` in cwd with env, in this process: its exit code and output."""
    out, err, code, here = io.StringIO(), io.StringIO(), 0, os.getcwd()
    with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "argv", [str(SCRIPT), *args]), \
            mock.patch.object(sys, "path", [str(SCRIPT.parent), *sys.path]), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        os.chdir(cwd)
        try:
            runpy.run_path(str(SCRIPT), run_name="__main__")
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else int(e.code is not None)
        finally:
            os.chdir(here)
    return subprocess.CompletedProcess(args, code, out.getvalue(), err.getvalue())


class Cases:
    """The tests, run by the two flavours below."""

    @classmethod
    def setUpClass(cls):
        """The repo is built once per class (git init and a commit are the slow part); each test gets a copy."""
        super().setUpClass()
        cls.template_dir = tempfile.TemporaryDirectory()
        cls.template = Path(os.path.realpath(cls.template_dir.name))
        cls.write_in(cls.template, ".gitignore", "target/\nnode_modules/\ndist/\n.secrets/\nnotes.txt\n"
                                                 "code/swift/libs/Hal2Core/Frameworks/\n")
        cls.write_in(cls.template, "code/rust/src/lib.rs", "")
        cls.write_in(cls.template, "dist/keep.txt", "tracked in an ignored folder\n")
        subprocess.run(["git", "init", "-q"], cwd=cls.template, env=ENV, check=True)
        subprocess.run(["git", "add", "-A"], cwd=cls.template, env=ENV, check=True)
        subprocess.run(["git", "add", "-f", "dist/keep.txt"], cwd=cls.template, env=ENV, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=cls.template, env=ENV, check=True)
        cls.write_in(cls.template, "code/rust/target/debug/big", "x" * 5000)
        cls.write_in(cls.template, "code/swift/libs/Hal2Core/Frameworks/Hal2Rust.xcframework/lib", "x")
        cls.write_in(cls.template, "web/node_modules/pkg/index.js", "x")
        cls.write_in(cls.template, "dist/out.js", "x")
        cls.write_in(cls.template, ".secrets/00/TOKEN", "secret")
        cls.write_in(cls.template, "notes.txt", "mine")

    @classmethod
    def tearDownClass(cls):
        cls.template_dir.cleanup()
        super().tearDownClass()

    @staticmethod
    def write_in(root, rel, text):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(os.path.realpath(self.tmp.name))
        shutil.copytree(self.template, self.repo, symlinks=True, dirs_exist_ok=True)
        bin_ = tempfile.TemporaryDirectory()
        self.addCleanup(bin_.cleanup)
        self.bin = Path(os.path.realpath(bin_.name))
        self.log = self.bin / "log"
        self.env = {**ENV, **self.prepare()}

    def prepare(self) -> dict:
        """The environment of this flavour on top of the process's."""
        raise NotImplementedError

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def invoke(self, cwd, args):
        """`python3 cleanup.py <args>` in cwd, a real process."""
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, env=self.env, text=True,
                              capture_output=True)

    def run_(self, *args):
        return self.invoke(self.repo / "code", args)

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

    def test_a_folder_holding_a_protected_path_is_kept_and_refused(self):
        """D32: also deep below an artifact folder, also when named."""
        self.write(".gitignore", "target/\nnode_modules/\ndist/\n.secrets/\nnotes.txt\nbuild/\napp/.env\n")
        self.write("build/sub/.env.local", "A=1\n")
        self.write("build/out.o", "x")
        self.write("app/.env", "A=3\n")
        rows = self.listing()
        self.assertEqual((rows["build"]["kind"], rows["build"]["rebuild"]), ("kept", "holds a protected path"))
        self.assertFalse(rows["build"]["selected"])
        self.assertEqual(rows["app"]["kind"], "kept")
        self.run_("delete")
        for rel in ("build/sub/.env.local", "app/.env"):
            self.assertTrue((self.repo / rel).exists(), rel)
        for rel in ("build", "app"):
            r = self.run_("delete", rel)
            self.assertEqual(r.returncode, 1)
            self.assertIn(f"skip    {rel}: holds a protected path", r.stdout)

    def test_the_shared_cases(self):
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=SCRIPT.parent, text=True,
                             capture_output=True).stdout.strip()
        cases = Path(top) / CASES if top else None
        if not cases or not cases.is_file():
            self.skipTest("the shared cases are hal2's: code/rust/libs/hal2-git/tests/fixtures/cleanup")
        for case in json.loads(cases.read_text())["cases"]:
            if case["links"] and sys.platform == "win32":
                continue
            with self.subTest(case=case["name"]), tempfile.TemporaryDirectory() as tmp:
                self.hold_case(Path(os.path.realpath(tmp)), case)

    def hold_case(self, top, case):
        def git(*args):
            subprocess.run(["git", *args], cwd=top, env={**os.environ, **GIT_ENV}, check=True)

        def put(rel, text):
            (top / rel).parent.mkdir(parents=True, exist_ok=True)
            (top / rel).write_text(text)

        git("init", "-q")
        put(".gitignore", case["gitignore"])
        if case["cleanup"] is not None:
            put(".hal/cleanup", case["cleanup"])
        for rel, text in case["tracked"].items():
            put(rel, text)
        git("add", "-A")
        for rel in case["tracked"]:
            git("add", "-f", rel)
        git("commit", "-qm", "init")
        for rel, text in case["files"].items():
            put(rel, text)
        for rel, target in case["links"].items():
            os.symlink(target, top / rel)

        def run(*args):
            return self.invoke(top, args)

        def paths(out):
            return sorted(m.group(1) for m in re.finditer(r"^(?:would delete|deleted)\s+\S+\s+(.*)$", out, re.M))

        for rel, why in case["refused"].items():
            r = run("delete", rel)
            self.assertEqual((r.returncode, f"skip    {rel}: {why}" in r.stdout), (1, True), (rel, r.stdout))
        listed = json.loads(run("list", "--json").stdout)["artifacts"]
        self.assertEqual({a["path"]: a["kind"] for a in listed}, case["list"])
        wanted = sorted(case["deleted"])
        dry = run("delete", "--dry-run")
        self.assertEqual((dry.returncode, paths(dry.stdout)), (0, wanted), dry.stdout)
        self.assertTrue(all((top / p).exists() for p in wanted), "a dry run deleted")
        done = run("delete")
        self.assertEqual((done.returncode, paths(done.stdout)), (0, wanted), done.stdout)
        self.assertFalse(any((top / p).exists() for p in wanted))
        for rel in case["kept"] + list(case["tracked"]):
            self.assertTrue((top / rel).exists(), f"{rel} was deleted")
        if case["named"]:
            named = run("delete", *case["named"])
            self.assertEqual((named.returncode, paths(named.stdout)), (0, sorted(case["named"])), named.stdout)


class PythonTest(Cases, unittest.TestCase):
    """HAL_CLEANUP_CLI="": the Python rule alone."""

    def prepare(self):
        return {"HAL_CLEANUP_CLI": ""}

    def invoke(self, cwd, args):
        """The Python rule needs no process of its own: the fake CLI's flavour runs the script as one."""
        return in_process(cwd, args, self.env)


class FakeCliTest(Cases, unittest.TestCase):
    """A fake hal2-cli-git on PATH, found by PATH alone."""

    def prepare(self):
        fake_cli(self.bin)
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "FAKE_LOG": str(self.log)}
        self.removed = os.environ.get("HAL_CLEANUP_CLI")
        return env

    def run_(self, *args):
        self.env.pop("HAL_CLEANUP_CLI", None)
        return super().run_(*args)

    def logged(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_the_arguments_arrive_unchanged_and_its_exit_code_is_the_skills(self):
        self.run_("list", "--json", "--worktree", "03")
        self.run_("delete", "--dry-run", "a b", "c")
        self.run_("busy")
        self.assertEqual(self.logged(), [["worktree", "cleanup", "list", "--json", "--worktree", "03"],
                                         ["worktree", "cleanup", "delete", "--dry-run", "a b", "c"],
                                         ["worktree", "cleanup", "busy"]])
        self.env["FAKE_CODE"] = "7"
        r = self.run_("delete")
        self.assertEqual((r.returncode, r.stdout), (7, "fake says hi\n"))

    def test_the_group_help_of_hal2_core_cli_counts_too(self):
        """hal2 plan 0318: on hal2_core::cli `worktree cleanup --help` is the group's list, `<bin> <words> - ...`."""
        fake_cli(self.bin, usage="hal2-cli-git worktree cleanup - The build artifacts of a checkout: list, busy, delete")
        self.run_("busy")
        self.assertEqual(self.logged(), [["worktree", "cleanup", "busy"]])

    def test_a_cli_that_fails_help_makes_the_python_run(self):
        fake_cli(self.bin, help_code=2)
        self.env["FAKE_CODE"] = "7"
        r = self.run_("list", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.logged(), [])
        self.assertIn("artifacts", json.loads(r.stdout))

    def test_an_older_cli_exiting_0_on_any_help_makes_the_python_run(self):
        """D32: the exit code alone is no proof; the first line of the help is."""
        fake_cli(self.bin, usage="usage: hal2-cli-git status [--json] [--repo <dir>]")
        self.env["FAKE_CODE"] = "7"
        r = self.run_("list", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.logged(), [])

    def test_a_cli_that_cannot_be_started_makes_the_python_run(self):
        broken = self.bin / "broken"
        broken.write_text("not a program")
        broken.chmod(0o755)
        self.env["HAL_CLEANUP_CLI"] = str(broken)
        self.env["FAKE_CODE"] = "7"
        r = super().run_("list", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("artifacts", json.loads(r.stdout))

    def test_hal_cleanup_cli_names_the_program_and_empty_means_none(self):
        other = self.bin / "other"
        other.mkdir()
        fake_cli(other)
        self.env["PATH"] = os.environ["PATH"]  # nothing on PATH
        self.env["HAL_CLEANUP_CLI"] = str(other / "hal2-cli-git")
        self.env["FAKE_CODE"] = "7"
        self.assertEqual(super().run_("busy").returncode, 7)
        self.env["HAL_CLEANUP_CLI"] = ""
        self.env["PATH"] = f"{self.bin}{os.pathsep}{os.environ['PATH']}"
        self.assertNotEqual(super().run_("busy").returncode, 7)


if __name__ == "__main__":
    unittest.main()
