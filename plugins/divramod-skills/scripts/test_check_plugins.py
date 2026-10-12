#!/usr/bin/env python3
"""Unit tests for check-plugins.py's per-folder prerequisite rule (offline)."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("check_plugins", Path(__file__).resolve().parent / "check-plugins.py")
check_plugins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_plugins)
prereq_errors = check_plugins.prereq_errors


class TestPrereqRule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skill = Path(self.tmp.name) / "skills" / "demo"
        (self.skill / "scripts").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, text: str = "", exe: bool = False) -> None:
        f = self.skill / "scripts" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        if exe:
            f.chmod(0o755)

    def prereqs(self, folder: str = "") -> None:
        for name in check_plugins.PREREQ_SCRIPTS:
            self.write(f"{folder}/{name}".lstrip("/"), "#!/bin/sh\n", exe=True)

    def test_no_tools_no_requirement(self):
        self.write("web/prepare.py", "import urllib.request\n")
        self.write("web/test_prepare.py", "import subprocess\n")  # tests don't count
        self.assertEqual(prereq_errors(self.skill), [])

    def test_source_folder_with_subprocess_needs_its_own_scripts(self):
        self.prereqs()
        self.write("video/prepare.py", "import subprocess\n")
        errors = prereq_errors(self.skill)
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("video" in e and "missing" in e for e in errors), errors)
        self.prereqs("video")
        self.assertEqual(prereq_errors(self.skill), [])

    def test_source_folder_needs_the_top_level_aggregators(self):
        self.write("video/prepare.py", "import subprocess\n")
        self.prereqs("video")
        errors = prereq_errors(self.skill)
        self.assertEqual([e.split(" ")[0] for e in errors],
                         ["skills/demo/scripts/check-prerequisites.sh", "skills/demo/scripts/install-prerequisites.sh"])

    def test_flat_scripts_folder_still_works(self):
        self.write("run.py", "import shutil\nshutil.which('jq')\n")
        self.assertEqual(len(prereq_errors(self.skill)), 2)
        self.prereqs()
        self.assertEqual(prereq_errors(self.skill), [])

    def test_not_executable(self):
        self.write("x/fetch.sh", "command -v curl\n")
        self.prereqs()
        self.prereqs("x")
        (self.skill / "scripts" / "x" / "install-prerequisites.sh").chmod(0o644)
        self.assertEqual(prereq_errors(self.skill), ["skills/demo/scripts/x/install-prerequisites.sh is not executable"])


if __name__ == "__main__":
    unittest.main()
