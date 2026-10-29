"""uat.py: plan resolution, the walk views and the verdict pass-through, against a fake hal2-cli-plans (plan 0364 step 6)."""

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import uat

PLAN = "0042-the-answer"
FAKE = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
log = os.environ["FAKE_LOG"]
open(log, "a").write(json.dumps(args) + "\\n")
if args[:2] == ["uat", "list"]:
    plan = args[args.index("--plan") + 1]
    if plan != "0042-the-answer":
        sys.stderr.write("hal2-cli-plans: plan %s has no uat.md\\n" % plan)
        sys.exit(1)
    print(open(os.environ["FAKE_DATA"]).read())
elif args[:2] == ["uat", "set"]:
    print("recorded " + " ".join(args[2:5]))
"""


def entry(key, state, outdated=False, **check):
    base = {"id": key, "title": f"Check {key}", "priority": "p1", "steps": ["Do it."], "expected": "It works.",
            "preconditions": [], "open": None, "run": None, "charter": None, "timebox": None}
    return {"key": key, "check": {**base, **check},
            "status": {"state": state, "outdated": outdated, "runs": 0, "latest": None}}


RECORD = {"slug": PLAN, "before": "Main is installed.", "checks": [
    entry("U1", "pass"), entry("U2", "untested", run="echo hi", preconditions=["A server runs."]),
    entry("U3", "fail"), entry("U4", "pass", outdated=True), entry("0041/U1", "untested"), entry("U5", "skip")]}


class UatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        for name in (PLAN, "0043-other-thing", "0044-other-more"):
            (self.root / "plans" / name).mkdir(parents=True)
        (self.root / "plans" / "CURRENT_PLAN").write_text(PLAN + "\n")
        self.log, self.data = self.tmp / "log", self.tmp / "data.json"
        self.data.write_text(json.dumps([RECORD]))
        fake = self.tmp / "fake-plans"
        fake.write_text(FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        env = {"HAL2_CLI_PLANS": str(fake), "FAKE_LOG": str(self.log), "FAKE_DATA": str(self.data)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = uat.main([*args, "--repo", str(self.root)])
        return code, out.getvalue(), err.getvalue()

    def cli_calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_plan_resolution(self):
        self.assertEqual(self.call("plan")[1], PLAN + "\n")  # CURRENT_PLAN
        self.assertEqual(self.call("plan", "42")[1], PLAN + "\n")  # a bare number
        self.assertEqual(self.call("plan", "0042")[1], PLAN + "\n")
        self.assertEqual(self.call("plan", "the-answer")[1], PLAN + "\n")  # the slug part
        self.assertEqual(self.call("plan", PLAN)[1], PLAN + "\n")
        code, _, err = self.call("plan", "other")  # two match
        self.assertEqual(code, 2)
        self.assertIn("several plans", err)
        self.assertEqual(self.call("plan", "99")[0], 2)

    def test_current_plan_may_sit_in_the_git_dir_only(self):
        (self.root / "plans" / "CURRENT_PLAN").unlink()
        (self.root / ".git" / "hal").mkdir(parents=True)
        (self.root / ".git" / "hal" / "CURRENT_PLAN").write_text(PLAN + "\n")
        self.assertEqual(self.call("plan")[1], PLAN + "\n")

    def test_current_plan_that_is_no_folder(self):
        (self.root / "plans" / "CURRENT_PLAN").write_text("shot/3/x\n")
        code, _, err = self.call("list")
        self.assertEqual(code, 2)
        self.assertIn("no plan folder", err)

    def test_list_groups_confirmed_open_and_the_rest(self):
        code, out, _ = self.call("list")
        self.assertEqual(code, 0)
        self.assertIn(f"{PLAN}: 1 of 6 confirmed, 3 open", out)  # U4 is an outdated pass: retest
        rows = {line.split()[0]: line.split()[2] for line in out.splitlines() if line.startswith("  ")}
        self.assertEqual(rows, {"U1": "confirmed", "U2": "open", "U3": "failed", "U4": "open", "0041/U1": "open", "U5": "skipped"})
        self.assertIn("not walked again unless you name them: U3, U5", out)
        data = json.loads(self.call("list", "--json")[1])
        self.assertEqual((data["confirmed"], data["open"], data["total"]), (1, 3, 6))

    def test_open_is_the_walk_in_file_order(self):
        code, out, _ = self.call("open")
        self.assertEqual(code, 0)
        keys = [line.split()[0] for line in out.splitlines() if line.startswith(("U", "0041/"))]
        self.assertEqual(keys, ["U2", "U4", "0041/U1"])
        self.assertIn("Before you start: Main is installed.", out)
        self.assertIn("Before: A server runs.", out)
        self.assertIn("Run: echo hi", out)
        self.assertIn("Expected: It works.", out)
        self.assertIn(f"Set: uat.py set {PLAN} U2 pass|fail|skip|blocked", out)

    def test_next_shows_only_the_first_open(self):
        out = self.call("next", "42")[1]
        self.assertIn("U2  Check U2", out)
        self.assertNotIn("U4  Check U4", out)

    def test_show_one_check_by_any_spelling(self):
        for args in (("show", "U3"), ("show", "42", "u3"), ("show", "42", "3"), ("show", PLAN, "U3")):
            code, out, _ = self.call(*args)
            self.assertEqual(code, 0, args)
            self.assertIn("U3  Check U3", out)
            self.assertNotIn("U2  Check", out)
        self.assertIn("0041/U1  Check", self.call("show", "0041/U1")[1])
        self.assertEqual(self.call("show", "U9")[0], 1)
        self.assertEqual(self.call("show")[0], 2)

    def test_the_uats_object_of_hal2_plan_0318(self):
        bare = self.call("list", "--json")
        self.data.write_text(json.dumps({"uats": [RECORD]}))
        self.assertEqual(self.call("list", "--json"), bare)
        self.assertEqual(bare[0], 0)

    def test_nothing_open(self):
        self.data.write_text(json.dumps([{**RECORD, "checks": [entry("U1", "pass")]}]))
        code, _, err = self.call("open")
        self.assertEqual(code, 1)
        self.assertIn("no open check", err)

    def test_plan_without_uat_md_fails_with_the_cli_message(self):
        code, _, err = self.call("list", "43")
        self.assertEqual(code, 1)
        self.assertIn("has no uat.md", err)

    def test_set_passes_through_to_the_cli(self):
        code, out, _ = self.call("set", "42", "u2", "fail", "--note", "button missing", "--shot")
        self.assertEqual(code, 0)
        self.assertIn("recorded", out)
        call = self.cli_calls()[-1]
        self.assertEqual(call[:5], ["uat", "set", PLAN, "U2", "fail"])
        self.assertEqual(call[5:7], ["--note", "button missing"])
        self.assertIn("--shot", call)
        self.assertEqual(call[-2:], ["--repo", str(self.root.resolve())])

    def test_set_uses_the_current_plan_and_checks_the_verdict_and_the_check(self):
        self.assertEqual(self.call("set", "U2", "pass")[0], 0)
        self.assertEqual(self.cli_calls()[-1][2:5], [PLAN, "U2", "pass"])
        self.assertEqual(self.call("set", "U2", "maybe")[0], 2)
        self.assertEqual(self.call("set", "U2")[0], 2)
        self.assertEqual(self.call("set", "pass")[0], 2)  # no check
        self.assertEqual(self.call("set", "U9", "pass")[0], 1)  # not in the plan
        self.assertEqual(len([c for c in self.cli_calls() if c[:2] == ["uat", "set"]]), 1)

    def test_bad_arguments(self):
        self.assertEqual(self.call("show", "U1", "U2")[0], 2)
        self.assertEqual(self.call("list", "--bogus")[0], 2)
        self.assertEqual(self.call("frobnicate")[0], 2)
        self.assertEqual(self.call("h")[0], 0)

    def test_missing_cli(self):
        with mock.patch.dict(os.environ, {"HAL2_CLI_PLANS": str(self.tmp / "nope")}):
            code, _, err = self.call("list")
        self.assertEqual(code, 1)
        self.assertIn("not installed", err)

    def test_split_args(self):
        self.assertEqual(uat.split_args(["364"]), ("364", None))
        self.assertEqual(uat.split_args(["U2"]), (None, "U2"))
        self.assertEqual(uat.split_args(["364", "2"]), ("364", "2"))
        self.assertEqual(uat.split_args(["slug-x", "0041/U1"]), ("slug-x", "0041/U1"))


if __name__ == "__main__":
    unittest.main()
