"""The temp repository the one plan shape's command tests run on (hal2 plan 0376, rows 7-8): a git repository in a
folder named `07` on the branch `07` (a field), plan.py run as the user runs it, shape.py's own overview render
(`$HAL2_CLI_PLANS` names no binary), and helpers that edit a sub-plan's or step's front matter in place."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import envelope
import shape
from shape_names import StepRef

SCRIPT = Path(__file__).resolve().parent / "plan.py"


def fixture() -> Path | None:
    """hal2-core's golden plan `code/rust/libs/hal2-core/tests/golden/plan-shape/`, read in place."""
    for folder in Path(__file__).resolve().parents:
        found = folder / "code/rust/libs/hal2-core/tests/golden/plan-shape"
        if found.is_dir():
            return found
    return None


class TempPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "07"
        self.root.mkdir()
        self.git("init", "-q", "-b", "07")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.git("config", "commit.gpgsign", "false")
        self.env = {**os.environ, shape.CLI_ENV: str(self.root / "no-cli")}

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args) -> str:
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout

    def run_plan(self, *args) -> subprocess.CompletedProcess:
        """plan.py with `args`; a `new` writes schema 2 here (its default is schema 1 until hal2 plan 0409)."""
        if args[:1] == ("new",) and "--schema" not in args:
            args = (*args, "--schema", "2")
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                              capture_output=True, text=True, cwd=self.root, env=self.env)

    def plan(self, *args) -> dict:
        result = self.run_plan(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def refused(self, *args) -> str:
        result = self.run_plan(*args)
        self.assertEqual(result.returncode, 1, (args, result.stdout))
        return result.stderr

    def new(self, *args) -> Path:
        return (self.root / self.plan("new", *args)["path"]).parent

    def edit_subplan(self, folder: Path, number: int, **keys) -> None:
        sub = shape.load(folder).subplan(number)
        doc = sub.copy_doc()
        for key, value in keys.items():
            setattr(doc, key, value)
        (folder / sub.file).write_text(doc.render())

    def edit_step(self, folder: Path, ref: str, **keys) -> None:
        shape.write_step(folder, StepRef.parse(ref), **keys)

    def set_plan_key(self, folder: Path, key: str, raw: str) -> None:
        path = folder / "plan.md"
        path.write_text(envelope.set_key(path.read_text(), key, raw))

    def commit_all(self, message: str = "wip") -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
