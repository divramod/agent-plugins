"""`plan.py check` and hal2's dependency scan (hal2 plan 0595 step 8): each undeclared wait `hal2-cli-plans depends
check --json` reports is a problem ending in `(plan-dependencies)`; a done plan is not scanned; an older CLI is one
skipped without a word and passes (`skipped` says why). The CLI is a stub answering both `depends check` and `questions check`.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "plan.py"
sys.path.insert(0, str(HERE))

import dcheck  # noqa: E402
import qcheck  # noqa: E402
import testkit  # noqa: E402

FINDING = {"plan": 514, "file": "decisions.md", "line": 5, "text": "Step 4 waits for plan 0514 to be pushed;"}
LINE = ("plans/0001-tiny/decisions.md:5: waits for 0514, not in depends_on: Step 4 waits for plan 0514 to be pushed; "
        "(plan-dependencies)")


def stub(folder: Path, depends: str, code: int) -> str:
    """A hal2-cli-plans that prints `depends` (exit `code`) for `depends ...` and a clean questions check else; it
    records its arguments in `args`."""
    path = folder / "hal2-cli-plans"
    questions = json.dumps({"store": "x", "problems": []})
    path.write_text(f"#!/bin/sh\necho \"$@\" >> '{folder}/args'\nif [ \"$1\" = depends ]; then\ncat <<'EOF'\n"
                    f"{depends}\nEOF\nexit {code}\nfi\ncat <<'EOF'\n{questions}\nEOF\n")
    path.chmod(0o755)
    return str(path)


def scanned(findings: list[dict]) -> str:
    plan = {"plan": 1, "slug": "0001-tiny", "declared": [], "findings": findings}
    return json.dumps({"schema": 1, "farm": "repo", "ok": not findings, "plans": [plan]})


class DCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "repo"
        self.bin = Path(self.tmp.name).resolve() / "bin"
        self.bin.mkdir()
        testkit.init_repo(self.root)
        result = testkit.run(SCRIPT, ["--root", str(self.root), "new", "Tiny", "--schema", "1"], cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.plan = self.root / json.loads(result.stdout)["path"]
        self.plan.write_text(re.sub(r"^- (Out|Proof): <.*>$", r"- \1: written", self.plan.read_text(), flags=re.M)
                             .replace("- Seed: <seedbag>#<n>\n", ""))

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, cli: str) -> subprocess.CompletedProcess:
        env = {**os.environ, qcheck.ENV: cli}
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "check"],
                              capture_output=True, text=True, env=env, cwd=self.root)

    def problems(self, result: subprocess.CompletedProcess) -> list[str]:
        return [line for line in result.stdout.splitlines() if line.endswith(f"({dcheck.RULE})")]

    def test_an_undeclared_wait_is_a_problem_ending_in_the_rule(self):
        result = self.check(stub(self.bin, scanned([FINDING]), 1))
        self.assertEqual(self.problems(result), [LINE])
        self.assertEqual(result.returncode, 1)
        calls = (self.bin / "args").read_text().splitlines()
        self.assertIn(f"depends check --json --repo {self.root} --plan 0001-tiny", calls)

    def test_only_the_current_plan_is_scanned(self):
        other = self.root / "plans" / "0002-other-plan"
        other.mkdir()
        (other / "plan.md").write_text(self.plan.read_text().replace("0001", "0002").replace("Tiny", "Other plan"))
        self.check(stub(self.bin, scanned([]), 0))
        calls = [c for c in (self.bin / "args").read_text().splitlines() if c.startswith("depends")]
        self.assertEqual(calls, [f"depends check --json --repo {self.root} --plan 0001-tiny"])
        (self.root / "plans" / "CURRENT_PLAN").unlink()
        (self.bin / "args").unlink()
        self.check(stub(self.bin, scanned([FINDING]), 1))
        calls = [c for c in (self.bin / "args").read_text().splitlines() if c.startswith("depends")]
        self.assertEqual(calls, [], "no current plan: none scanned")

    def test_a_clean_scan_passes(self):
        result = self.check(stub(self.bin, scanned([]), 0))
        self.assertEqual(self.problems(result), [])

    def test_a_done_plan_is_not_scanned(self):
        self.plan.write_text(self.plan.read_text().replace("status: open", "status: done", 1))
        self.check(stub(self.bin, scanned([FINDING]), 1))
        calls = (self.bin / "args").read_text().splitlines()
        self.assertFalse([c for c in calls if c.startswith("depends")], calls)

    def test_an_older_cli_is_skipped_without_a_word_and_passes(self):
        cli = stub(self.bin, "hal2-cli-plans: unrecognized subcommand 'depends'", 2)
        result = self.check(cli)
        self.assertEqual((self.problems(result), result.returncode), ([], 0))
        self.assertNotIn("depends", result.stdout + result.stderr)
        with mock.patch.dict(os.environ, {qcheck.ENV: cli}):
            self.assertEqual(dcheck.skipped(self.root), dcheck.TOO_OLD)


if __name__ == "__main__":
    unittest.main()
