"""The spec skill's test kit: a fresh git repository per test and spec.py run in process (no real farm, record
tests-leave-nothing). `RECORDS` is the branch's hal2-cli-records (`$HAL2_CLI_RECORDS`, else code/rust/target/debug of
this checkout, else the one on PATH); the tests needing it are skipped without."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("HAL2_OVERLAP", "off")  # the start paths' overlap scan (~25 s) has its own tests
sys.path.insert(0, str(HERE))

import spec  # noqa: E402
import envelope  # noqa: E402  (the plan skill's, put on the path by spec)
import plan_number  # noqa: E402


def records_cli() -> str | None:
    named = os.environ.get("HAL2_CLI_RECORDS")
    if named:
        return named
    for parent in HERE.parents:
        built = parent / "code/rust/target/debug/hal2-cli-records"
        if built.is_file():
            return str(built)
    return shutil.which("hal2-cli-records")


RECORDS = records_cli()
FILLED = {
    "<what hurts today, for whom, and why now>": "Logging in needs a password nobody remembers.",
    "<who uses it, in which situation>": "every member, on a new device",
    "<a goal, as \"the system SHALL ...\">": "the system SHALL log a member in with a passkey",
    "<what it deliberately does not try>": "no password reset",
    "<what the feature covers>": "passkey sign-up and login",
    "<what it leaves out, and where that goes>": "recovery (a later plan)",
    "<the system SHALL ...>": "the system SHALL store only the public key",
    "<stack, platforms, budgets and guardrails it must keep>": "WebAuthn, under 300 ms",
    "<a state>": "a member with a passkey", "<an action>": "they log in", "<the observable result>": "they see home",
    "<what needs designing: `/design create` writes design.html beside this file; or \"nothing to design\" for a simple "
    "feat>": "the login screen and its flow: [design.html](design.html)",
}


class SpecCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        (self.root / "plans" / "0007-older-plan").mkdir(parents=True)
        (self.root / "plans" / "0007-older-plan" / "plan.md").write_text("# Plan 0007: older plan\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_spec(self, *args) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = spec.main(["--repo", str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def new(self, title: str = "Login with passkeys") -> dict:
        code, out, err = self.run_spec("new", title, "--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def fill(self, info: dict) -> Path:
        path = self.root / info["spec"]
        text = path.read_text()
        for old, new in FILLED.items():
            text = text.replace(old, new)
        path.write_text(text)
        return path


    def problems(self) -> list:
        """The branch records checker's problems over the scratch repository (the test needs RECORDS)."""
        out = subprocess.run([RECORDS, "check", "--json", "--repo", str(self.root)], capture_output=True, text=True)
        return json.loads(out.stdout)["problems"]

    def plan_text(self, info: dict) -> str:
        return (self.root / info["plan"]).read_text()

    def add_steps(self, info: dict) -> None:
        """Plan the spec's plan by hand: a step row, status open (what `/plan` will do, plan 0502 step 6)."""
        path = self.root / info["plan"]
        row = "| # | Step | Done when | Status |\n|---|---|---|---|\n| 1 | a step | it passes | next |\n"
        path.write_text(path.read_text().replace("status: spec", "status: open")
                        .replace("## Pre-authorized", f"## Steps\n\n{row}\n## Pre-authorized"))
