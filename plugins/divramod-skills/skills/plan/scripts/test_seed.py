"""Plan 0293 step 4: `plan.py new --seed <seedbag>#<n>` writes the Context's `- Seed:` line and marks the seed sent
through hal2-cli-shooter. Every test runs a fake CLI (a script in a temporary folder, named by $HAL2_CLI_SHOOTER, that
records its arguments): the real one never touches the user's seedbags."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "plan.py"
sys.path.insert(0, str(HERE))

import seed  # noqa: E402

LISTING = {"shotfiles": "/x", "shots": [
    {"id": 1, "file": "skill-plan", "number": "1", "title": "plan   names\tare short", "body": "b"},
    {"id": 2, "file": "skill-plan", "number": "3", "title": "another", "body": "b"}]}

FAKE = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
case "$2" in
  list-open) printf '%s\n' "$FAKE_LISTING" ;;
  mark-sent) [ "$FAKE_MARK_FAILS" = 1 ] && { echo 'hal2-cli-shooter: disk full' >&2; exit 1; }; echo '{}' ;;
esac
"""


class SeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root, self.log = base / "repo", base / "log"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        self.cli = base / "fake-shooter"
        self.cli.write_text(FAKE)
        self.cli.chmod(0o755)
        self.env = {"PATH": "/usr/bin:/bin", "HAL2_CLI_SHOOTER": str(self.cli), "FAKE_LOG": str(self.log),
                    "FAKE_LISTING": json.dumps(LISTING)}

    def tearDown(self):
        self.tmp.cleanup()

    def new(self, *args, **env) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "new", "Tiny", *args],
                              capture_output=True, text=True, env={**self.env, **env})

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def context(self, result) -> str:
        return (self.root / json.loads(result.stdout)["path"]).read_text()

    def test_a_seed_is_written_into_the_context_and_marked_sent(self):
        result = self.new("--seed", "skill-plan#1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- Seed: skill-plan#1 (plan names are short)\n", self.context(result))
        self.assertNotIn("<seedbag>", self.context(result))
        self.assertEqual(json.loads(result.stdout)["seed"],
                         {"ref": "skill-plan#1", "title": "plan names are short", "why": "", "marked": True})
        self.assertEqual(self.calls(), ["shots list-open skill-plan --json",
                                        "shots mark-sent skill-plan 1 --worktree main"])

    def test_a_worktree_marks_the_seed_with_its_folder_name(self):
        wt = Path(self.tmp.name).resolve() / "wt" / "05"
        wt.mkdir(parents=True)
        (wt / ".git").write_text("gitdir: /elsewhere\n")
        self.assertEqual(seed.worktree_name(wt, False), "05")
        self.assertEqual(seed.worktree_name(wt, True), "wt/05")
        self.assertEqual(seed.worktree_name(self.root, False), "main")
        self.assertEqual(seed.worktree_name(self.root, True), "repo/main")

    def test_a_global_seedbag_is_read_and_marked_with_global(self):
        result = self.new("--seed", "global:skill-plan#3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- Seed: global:skill-plan#3 (another)\n", self.context(result))
        self.assertEqual(self.calls(), ["shots list-open skill-plan --global --json",
                                        "shots mark-sent skill-plan 3 --worktree repo/main --global"])

    def test_no_seed_leaves_the_placeholder_line_out(self):
        result = self.new()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Seed", self.context(result))
        self.assertNotIn("seed", json.loads(result.stdout))
        self.assertEqual(self.calls(), [])

    def test_a_missing_cli_still_makes_the_plan_with_the_line(self):
        result = self.new("--seed", "skill-plan#1", HAL2_CLI_SHOOTER=str(self.cli) + "-gone")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- Seed: skill-plan#1\n", self.context(result))
        info = json.loads(result.stdout)["seed"]
        self.assertFalse(info["marked"])
        self.assertIn("not installed", info["why"])

    def test_an_unknown_or_sent_seed_is_not_marked_and_does_not_fail_new(self):
        result = self.new("--seed", "skill-plan#9")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- Seed: skill-plan#9\n", self.context(result))
        info = json.loads(result.stdout)["seed"]
        self.assertFalse(info["marked"])
        self.assertIn("no open seed 9", info["why"])
        self.assertEqual(self.calls(), ["shots list-open skill-plan --json"])

    def test_a_seed_the_cli_cannot_mark_does_not_fail_new(self):
        result = self.new("--seed", "skill-plan#1", FAKE_MARK_FAILS="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(result.stdout)["seed"]
        self.assertEqual((info["marked"], info["why"]), (False, "hal2-cli-shooter: disk full"))
        self.assertIn("- Seed: skill-plan#1 (plan names are short)\n", self.context(result))

    def test_a_bad_value_fails_before_anything_is_created(self):
        for value in ("skill-plan", "skill-plan#", "#1", "skill-plan#0", "a b#1", "skill-plan#1x"):
            result = self.new("--seed", value)
            self.assertEqual(result.returncode, 1, value)
            self.assertIn("<seedbag>#<n>", result.stderr)
        self.assertFalse((self.root / "plans").exists())
        self.assertEqual(self.calls(), [])

    def test_parse(self):
        self.assertEqual(seed.parse("skill-plan#12"), ("skill-plan", "12", False))
        self.assertEqual(seed.parse("global:_ideas#4"), ("_ideas", "4", True))
        with self.assertRaises(seed.SeedError):
            seed.parse("global:#4")


if __name__ == "__main__":
    unittest.main()
