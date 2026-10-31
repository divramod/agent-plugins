"""The skill is a caller of `hal2-cli-projects new`: its arguments map to the CLI's, the CLI's answer and exit pass
through. The project logic is tested in hal2-projects and hal2-cli-projects. Run: python3 -m unittest test_create_project"""
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "create_project.py"


class Caller(unittest.TestCase):
    def run_with_fake(self, *args: str, code: int = 0) -> tuple[subprocess.CompletedProcess, list[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir, log = Path(tmp) / "bin", Path(tmp) / "argv"
            bin_dir.mkdir()
            fake = bin_dir / "hal2-cli-projects"
            fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}"\necho out\nexit {code}\n')
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"}
            r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env)
            return r, log.read_text().split() if log.exists() else []

    def test_dry_run_is_new_plan_without_yes(self):
        r, argv = self.run_with_fake("site", "st", "--dry-run", "--json")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(argv[:2], ["new", "plan"])
        self.assertNotIn("--yes", argv)
        self.assertIn("--json", argv)
        self.assertEqual(argv[argv.index("--alias") + 1], "st")

    def test_apply_needs_yes_and_maps_owner_and_smug(self):
        r, argv = self.run_with_fake("site", "st", "--owner", "me", "--smug", "a.yml,b.yml")
        self.assertEqual(argv[:2], ["new", "apply"])
        self.assertIn("--yes", argv)
        self.assertEqual(argv[argv.index("--owner") + 1], "me")
        self.assertEqual(argv.count("--smug"), 2)
        self.assertEqual(r.stdout, "out\n")

    def test_the_cli_exit_passes_through(self):
        r, _ = self.run_with_fake("site", "st", code=3)
        self.assertEqual(r.returncode, 3)

    def test_a_missing_cli_exits_2(self):
        env = {**os.environ, "PATH": "/usr/bin:/bin"}
        r = subprocess.run([sys.executable, str(SCRIPT), "x", "y"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
