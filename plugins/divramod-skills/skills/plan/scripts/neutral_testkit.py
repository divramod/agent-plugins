"""The neutral-commits tests' kit (no test here; hal2 plan 0409 D15, step 11), shared by the plan, git-push, handoff and
tollman tests: a fake `hal2-cli-plans` (an executable script that answers `commits --json` and records every other call
into a file) and a checkout whose git config has a `hal.farm`. Other skills load this file by its path (never this
folder on sys.path), then use `planread` from it.

  fake = FakeCli(tmp_dir, neutral=True)      fake.path; fake.calls() -> ["link-commit --next --plan ...", ...]
  farm(repo)                                  git config hal.farm for the checkout
  with env(fake): ...                         HAL2_CLI_PLANS set, planread's cache cleared before and after
"""
import contextlib
import importlib.util
import os
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent


def _load(name: str):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


planread = _load("planread")


class FakeCli:
    """`commits` prints `answer` and exits `code`; `link-commit` and anything else is recorded (its arguments) in
    `calls.log` and answers `{"linked": true}`. A `commits` call is recorded as well, so a cache can be counted."""

    def __init__(self, folder: Path, answer: str = '{"neutral": true, "why": "setting"}', code: int = 0):
        self.folder = Path(folder)
        self.log = self.folder / "calls.log"
        self.path = self.folder / "hal2-cli-plans"
        self.path.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >> "{self.log}"\n'
            'if [ "$1" = commits ]; then\n'
            f"  printf '%s\\n' {shlex.quote(answer)}\n  exit {code}\n"
            "fi\n"
            'echo \'{"linked": true}\'\n')
        self.path.chmod(self.path.stat().st_mode | stat.S_IXUSR)

    def calls(self, command: str = "") -> list[str]:
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        return [line for line in lines if line.startswith(command)]

    def links(self) -> list[str]:
        return self.calls("link-commit")


def farm(repo: Path, farm_id: str = "f-test") -> None:
    subprocess.run(["git", "-C", str(repo), "config", "hal.farm", farm_id], check=True)


@contextlib.contextmanager
def env(fake: "FakeCli | None"):
    """HAL2_CLI_PLANS names the fake (or nothing: a missing CLI); planread's per-process answers are forgotten."""
    named = str(fake.path) if fake else str(HERE / "no-such-cli")
    with mock.patch.dict(os.environ, {"HAL2_CLI_PLANS": named}):
        planread.fresh()
        try:
            yield
        finally:
            planread.fresh()
