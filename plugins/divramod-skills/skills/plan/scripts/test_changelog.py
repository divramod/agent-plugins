"""plan.py changelog: the plan's changelog fragment (hal2 plan 0339, record changelog-fragments)."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "plan.py"


class ChangelogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_plan(self, *args, cli=None) -> subprocess.CompletedProcess:
        env = {**os.environ, "PATH": "/usr/bin:/bin"}
        env.pop("HAL2_CLI_CHANGELOG", None)
        if cli:
            env["HAL2_CLI_CHANGELOG"] = str(cli)
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                              capture_output=True, text=True, env=env, cwd=self.root)

    def plan(self, *args, cli=None) -> dict:
        result = self.run_plan(*args, cli=cli)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_the_new_plan_row_asks_for_the_fragment_and_keeps_the_uat_prefix(self):
        last = self.plan("new", "plugin-plan 3 tabs")["steps"][-1]
        self.assertTrue(last["step"].startswith("Write the UATs and the changelog fragment: `uat.md` and `changelog.md`"))
        self.assertIn("hal2-cli-changelog check", last["done_when"])

    def test_without_the_cli_the_skill_writes_the_same_template_once(self):
        info = self.plan("new", "plugin-plan 3 tabs")
        self.assertEqual(info["changelog"], "")
        info = self.plan("changelog")
        text = (self.root / info["changelog"]).read_text()
        self.assertTrue(text.startswith("---\ntype: Changelog\nschema: 1\nplan: 1\ntitle: Changelog of plan 0001\n"), text)
        self.assertTrue(text.endswith("# Changelog of plan 0001\n\n## Added\n\n"))
        self.assertIn("hal2-cli-changelog check", info["changelog_next"])
        self.assertIn("not installed", info["changelog_next"])
        (self.root / info["changelog"]).write_text("edited\n")
        again = self.plan("changelog")
        self.assertEqual((self.root / again["changelog"]).read_text(), "edited\n")  # never overwritten
        self.assertTrue(again["changelog_next"].startswith("exists"))

    def test_with_the_cli_it_writes_the_fragment(self):
        info = self.plan("new", "plugin-plan 3 tabs")
        fake = self.root / "fake-changelog"
        fake.write_text('#!/bin/sh\n[ "$1 $2 $3" = "new 0001-plugin-plan-3-tabs --json" ] || exit 9\n'
                        'echo "from the cli" > plans/0001-plugin-plan-3-tabs/changelog.md\necho "{}"\n')
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        info = self.plan("changelog", cli=fake)
        self.assertEqual((self.root / info["changelog"]).read_text(), "from the cli\n")
        self.assertNotIn("not installed", info["changelog_next"])

    def test_a_failing_cli_is_reported_not_papered_over(self):
        self.plan("new", "plugin-plan 3 tabs")
        fake = self.root / "fake-changelog"
        fake.write_text('#!/bin/sh\necho \'{"error":{"message":"boom"}}\'\nexit 4\n')
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        result = self.run_plan("changelog", cli=fake)
        self.assertEqual(result.returncode, 1)
        self.assertIn("hal2-cli-changelog new: boom", result.stderr)

    def test_a_research_plan_gets_none(self):
        self.plan("new", "Compare tabs", "--research")
        result = self.run_plan("changelog")
        self.assertEqual(result.returncode, 1)
        self.assertIn("research plan writes no changelog", result.stderr)
        self.assertFalse(list(self.root.glob("plans/*/changelog.md")))


if __name__ == "__main__":
    unittest.main()
