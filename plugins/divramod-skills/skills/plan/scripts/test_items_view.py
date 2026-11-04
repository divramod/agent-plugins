"""plan.py current: the plan's gaps and manual items (items_view.py, hal2 plan 0595 step 3)."""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import testkit

SCRIPT = Path(__file__).resolve().parent / "plan.py"
GAP = """---
type: Gap
schema: 1
plan: 1
n: {n}
title: "{title}"
state: {state}
created: 2026-11-03
found_in: "2"
{route}---

# Gap {n:02}: {title}

## Missing

x

## Why

y

## Fix

z
"""
MANUAL = """---
type: Manual
schema: 1
plan: 1
n: 1
title: "Install the stick"
state: {state}
created: 2026-11-03
from: Q2
waits: "step 4"
---

# Manual 01: Install the stick

## Why

hands

## Steps

1. go

## Done when

booted
"""


class ItemsViewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        testkit.init_repo(self.root)
        self.bin = tempfile.TemporaryDirectory()  # a PATH with git only: the machine's hal2-cli-plans stays hidden
        self.addCleanup(self.bin.cleanup)
        self.addCleanup(self.tmp.cleanup)
        (Path(self.bin.name) / "git").symlink_to(shutil.which("git"))

    def current(self, cli: Path | None = None) -> dict:
        env = {**os.environ, "PATH": self.bin.name}
        env.pop("HAL2_CLI_PLANS", None)
        env["HAL2_CLI_PLANS"] = str(cli) if cli else ""
        result = testkit.run(SCRIPT, ["--root", str(self.root), "current"], env=env, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def folder(self) -> Path:
        result = testkit.run(SCRIPT, ["--root", str(self.root), "new", "items view"],
                             env={**os.environ, "PATH": self.bin.name}, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.root / json.loads(result.stdout)["path"].rsplit("/", 1)[0]

    def write(self, folder: Path, kind: str, name: str, text: str):
        (folder / kind).mkdir(exist_ok=True)
        (folder / kind / name).write_text(text)

    def test_a_plan_without_items_shows_none(self):
        self.folder()
        info = self.current()
        self.assertEqual(info["gaps"], {"open": 0, "total": 0, "items": [], "source": "files"})
        self.assertEqual(info["manual"]["open"], 0)

    def test_the_files_are_read_when_there_is_no_cli(self):
        folder = self.folder()
        self.write(folder, "gaps", "01-open-gap.md", GAP.format(n=1, title="Open gap", state="open", route=""))
        self.write(folder, "gaps", "02-routed.md", GAP.format(n=2, title="Routed", state="routed", route="route: servant 31\n"))
        self.write(folder, "gaps", "03-closed.md", GAP.format(n=3, title="Closed", state="closed", route=""))
        self.write(folder, "manual", "01-stick.md", MANUAL.format(state="open"))
        info = self.current()
        self.assertEqual((info["gaps"]["open"], info["gaps"]["total"], info["gaps"]["source"]), (2, 3, "files"))
        self.assertEqual(info["gaps"]["items"], [
            {"n": 1, "title": "Open gap", "state": "open", "route": ""},
            {"n": 2, "title": "Routed", "state": "routed", "route": "servant 31"},
            {"n": 3, "title": "Closed", "state": "closed", "route": ""}])
        self.assertEqual(info["manual"]["items"], [
            {"n": 1, "title": "Install the stick", "state": "open", "from": "Q2", "waits": "step 4"}])
        self.write(folder, "manual", "01-stick.md", MANUAL.format(state="done"))
        done = self.current()["manual"]
        self.assertEqual((done["open"], done["total"], done["items"][0]["state"]), (0, 1, "done"))

    def test_a_file_that_does_not_parse_is_a_problem_not_a_crash(self):
        folder = self.folder()
        self.write(folder, "gaps", "01-broken.md", "---\ntype: Gap\nn: 1\nstate:\n---\n")
        info = self.current()["gaps"]
        self.assertEqual((info["open"], len(info["problems"])), (0, 1))
        self.assertIn("01-broken.md", info["problems"][0])

    def test_the_cli_answers_when_it_has_the_command(self):
        folder = self.folder()
        self.write(folder, "gaps", "01-from-file.md", GAP.format(n=1, title="From file", state="open", route=""))
        fake = self.root / "fake-plans"
        answer = {"schema": 1, "items": [{"id": "x/0001/04", "n": 4, "title": "From cli", "state": "open", "route": None}],
                  "problems": []}
        fake.write_text("#!/bin/sh\n[ \"$1 $2\" = \"gaps list\" ] || exit 2\n"
                        f"echo '{json.dumps(answer)}'\n")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        info = self.current(fake)
        self.assertEqual(info["gaps"]["source"], "cli")
        self.assertEqual(info["gaps"]["items"], [{"n": 4, "title": "From cli", "state": "open", "route": ""}])
        self.assertEqual(info["manual"]["source"], "files")  # an older CLI (exit 2) leaves the files


if __name__ == "__main__":
    unittest.main()
