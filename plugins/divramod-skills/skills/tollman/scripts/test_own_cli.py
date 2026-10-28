"""Hal2 plan 0431 step 4: the CLI a tollman call runs on a candidate (own_cli.py, proof.py's records check). The hook
`.hal/own-cli.sh` is a real executable script over a temporary field; no cargo runs.
Enforces the record gate-binaries-not-older-than-candidate."""

import shutil
import stat
import tempfile
import unittest
from pathlib import Path

import own_cli
import proof
import test_proof


def hook(field: Path, body: str) -> Path:
    path = field / own_cli.HOOK
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class Resolve(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)

    def resolve(self, run=proof.sh):
        return own_cli.resolve(str(self.d), "hal2-cli-records", "main", "abc", run)

    def test_no_hook_keeps_the_installed_cli(self):
        self.assertEqual(self.resolve(), "hal2-cli-records")

    def test_a_hook_that_is_not_executable_is_no_hook(self):
        (self.d / ".hal").mkdir()
        (self.d / own_cli.HOOK).write_text("exit 1\n")
        self.assertEqual(self.resolve(), "hal2-cli-records")

    def test_the_hook_names_a_path_and_that_path_is_the_command(self):
        hook(self.d, 'printf "%s\\t/x/target/debug/%s\\tchanged\\n" "$1" "$1"\n')
        self.assertEqual(self.resolve(), "/x/target/debug/hal2-cli-records")

    def test_an_empty_path_keeps_the_installed_cli(self):
        hook(self.d, 'printf "%s\\t\\tinstalled\\n" "$1"\n')
        self.assertEqual(self.resolve(), "hal2-cli-records")

    def test_the_hook_gets_the_app_the_range_and_runs_in_the_field(self):
        hook(self.d, 'printf "%s\\t%s|%s|%s\\tx\\n" "$1" "$HAL_GATE_BASE" "$HAL_GATE_HEAD" "$(pwd -P)"\n')
        got = self.resolve()
        self.assertEqual(got, f"main|abc|{self.d.resolve()}")

    def test_a_failing_hook_cannot_run_the_check(self):
        hook(self.d, "echo 'build failed' >&2\nexit 1\n")
        self.assertIsNone(self.resolve())

    def test_a_hook_that_names_no_app_cannot_run_the_check(self):
        hook(self.d, 'echo "hal2-cli-git\\t\\tinstalled"\n')
        self.assertIsNone(self.resolve())

    def test_a_timed_out_hook_cannot_run_the_check(self):
        hook(self.d, "exec sleep 5\n")
        short = lambda argv, cwd: proof.sh(argv, cwd, timeout=0.2)  # noqa: E731
        self.assertIsNone(self.resolve(short))

    def test_build_output_on_stderr_does_not_hide_the_path(self):
        hook(self.d, 'echo "Compiling x" >&2\nprintf "%s\\t/p/%s\\tchanged\\n" "$1" "$1"\n')
        self.assertEqual(self.resolve(), "/p/hal2-cli-records")


class Proof(test_proof.Field):
    """The records check of a car's proof takes the hook's CLI; the names check is not affected."""

    def seen(self):
        """The records check runs the real hook; its command is recorded, its answer faked."""
        self.argvs = []

        def run_(argv, cwd):
            if argv[0] == "git" or argv[0] == "env":
                return proof.sh(argv, cwd)
            self.argvs.append(argv)
            return self.answers.get("records" if argv[0] != "python3" else "names", (0, "ok"))

        return lambda head: proof.verdict("-", self.d, head, "main", run=run_, cache=self.cache)

    def test_the_hooks_path_runs_the_records_check(self):
        hook(Path(self.d), 'printf "%s\\t/own/%s\\tchanged\\n" "$1" "$1"\n')
        self.g("add", "-A")
        self.g("commit", "-q", "-m", "hook")
        self.names_script()
        head = self.commit({"docs/x.md": "x\n"})
        v = self.seen()(head)
        self.assertEqual((v["state"], v["checks"]), ("green", ["names", "records"]))
        self.assertEqual([a[0] for a in self.argvs if "check" in a and a[0] != "python3"], ["/own/hal2-cli-records"])

    def test_no_hook_runs_the_installed_records_cli(self):
        self.names_script()
        head = self.commit({"docs/x.md": "x\n"})
        v = self.seen()(head)
        self.assertEqual(v["checks"], ["names", "records"])
        self.assertEqual([a[0] for a in self.argvs if a[0] != "python3"], ["hal2-cli-records"])

    def test_a_failing_hook_skips_the_records_check_never_red(self):
        hook(Path(self.d), "exit 1\n")
        self.names_script()
        head = self.commit({"docs/x.md": "x\n"})
        self.answers["records"] = (1, "docs/x.md:1: would be red")
        v = self.seen()(head)
        self.assertEqual((v["state"], v["checks"], v["skipped"]), ("green", ["names"], ["records"]))
        self.assertEqual([a for a in self.argvs if a[0] != "python3"], [], "the records CLI never ran")


if __name__ == "__main__":
    unittest.main()
