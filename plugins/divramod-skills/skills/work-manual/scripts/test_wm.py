"""wm.py lists, shows and ticks off the manual items of every farm through hal2-cli-plans (plan 0595 step 5).

The CLI is a stub script in a temp dir ($HAL2_CLI_PLANS) that answers from JSON files and logs its calls; the farms
are folders below a scratch home ($HAL2_HOME): never the real farms.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "wm.py"

STUB = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
root = os.environ["STUB_DIR"]
open(os.path.join(root, "calls.log"), "a").write(" ".join(args) + "\\n")
farm = os.path.basename(args[args.index("--repo") + 1])
fail = os.path.join(root, farm + ".fail")
if os.path.exists(fail):
    sys.stderr.write(open(fail).read())
    sys.exit(3)
if args[:2] == ["manual", "list"]:
    state = args[args.index("--state") + 1]
    items = json.load(open(os.path.join(root, farm + ".json")))
    keep = [i for i in items if state == "all" or i["state"] == state]
    print(json.dumps({"schema": 1, "kind": "manual", "farm": farm, "scope": "farm", "plan": None, "state": state,
                      "items": keep, "problems": [{"file": "plans/0001-x/manual/09-bad.md", "message": "no front matter"}]
                      if farm == "alpha" else []}))
elif args[:2] == ["manual", "done"]:
    print("manual " + args[2] + " done: plans/x/manual/01-y.md")
else:
    sys.exit(2)
"""


def item(farm, plan, n, title, **more):
    base = {"id": f"{farm}/{plan[:4]}/{n:02d}", "slug": plan, "checkout": "main", "plan": int(plan[:4]), "n": n,
            "title": title, "state": "open", "created": "2026-11-03", "closed": None, "from": None, "waits": None,
            "why": "Because.", "steps": "1. **Terminal**: do it.", "done_when": "It shows ok.", "extra": []}
    base.update(more)
    return base


class Wm(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.home, self.stub = base / "home", base / "stub"
        self.stub.mkdir()
        for name, plans in (("alpha", True), ("beta", True), ("noplans", False)):
            farm = self.home / "a" / name
            (farm / ".git").mkdir(parents=True)
            if plans:
                (farm / "plans").mkdir()
        (self.home / "a" / ".hidden" / ".git").mkdir(parents=True)
        (self.home / "a" / ".hidden" / "plans").mkdir()
        (self.home / "a" / "notarepo" / "plans").mkdir(parents=True)
        cli = self.stub / "hal2-cli-plans"
        cli.write_text(STUB)
        cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
        self.put("alpha", [item("alpha", "0391-gaps", 1, "Install the cable", waits="plan 0391 step 4"),
                           item("alpha", "0391-gaps", 2, "Done already", state="done", closed="2026-11-03"),
                           item("alpha", "0100-x", 3, "Click in the console", **{"from": 23})])
        self.put("beta", [])
        self.env = {**os.environ, "HAL2_HOME": str(self.home), "HAL2_CONFIG_DIR": str(self.home / "cfg"),
                    "HAL2_CLI_PLANS": str(cli), "STUB_DIR": str(self.stub)}

    def put(self, farm, items):
        (self.stub / f"{farm}.json").write_text(json.dumps(items))

    def wm(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=self.env,
                              check=False)

    def calls(self):
        return (self.stub / "calls.log").read_text().splitlines()

    def test_list_groups_open_items_by_farm_and_plan_one_line_each(self):
        out = self.wm("list")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.splitlines()[:7], [
            "alpha",
            "  0100-x",
            "    alpha/0100/03  Click in the console",
            "  0391-gaps",
            "    alpha/0391/01  Install the cable  (waits: plan 0391 step 4)",
            "problem: alpha: plans/0001-x/manual/09-bad.md: no front matter",
            "2 open manual items in 1 of 2 farms",
        ])
        self.assertNotIn("Done already", out.stdout)

    def test_list_asks_only_farms_with_a_plans_folder_through_the_cli(self):
        self.wm("list")
        repos = sorted(c.split("--repo ")[1].rsplit("/", 1)[1] for c in self.calls())
        self.assertEqual(repos, ["alpha", "beta"])
        self.assertTrue(all(c.startswith("manual list --farm --state open --json --repo ") for c in self.calls()))

    def test_root_comes_from_git_toml(self):
        other = self.home / "farms"
        (other / "gamma" / ".git").mkdir(parents=True)
        (other / "gamma" / "plans").mkdir()
        self.put("gamma", [item("gamma", "0007-z", 1, "Plug it in")])
        (self.home / "cfg").mkdir()
        (self.home / "cfg" / "git.toml").write_text('root = "~/farms"\n')
        out = self.wm("list")
        self.assertIn("gamma/0007/01  Plug it in", out.stdout)
        self.assertNotIn("alpha", out.stdout)

    def test_a_failing_farm_is_a_problem_line_and_the_rest_still_lists(self):
        (self.stub / "beta.fail").write_text("error: broken store\n")
        out = self.wm("list")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("problem: beta: hal2-cli-plans manual list failed (exit 3): error: broken store", out.stdout)
        self.assertIn("alpha/0391/01", out.stdout)

    def test_a_missing_cli_is_a_problem_per_farm_not_a_stop(self):
        self.env["HAL2_CLI_PLANS"] = str(self.stub / "nonexistent")
        out = self.wm("list")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("problem: alpha: hal2-cli-plans manual list failed (exit 127)", out.stdout)
        self.assertIn("0 open manual items in 0 of 2 farms", out.stdout)

    def test_list_json_carries_a_schema_the_items_and_the_problems(self):
        doc = json.loads(self.wm("list", "--json").stdout)
        self.assertEqual(doc["schema"], 1)
        self.assertEqual([f["farm"] for f in doc["farms"]], ["alpha"])
        self.assertEqual([i["id"] for i in doc["farms"][0]["items"]], ["alpha/0391/01", "alpha/0100/03"])
        self.assertEqual(len(doc["problems"]), 1)

    def test_show_prints_why_steps_and_done_when_as_stored(self):
        out = self.wm("show", "alpha/0100/03")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("alpha/0100/03  Click in the console", out.stdout)
        self.assertIn("from: Q23", out.stdout)
        self.assertIn("## Why\nBecause.", out.stdout)
        self.assertIn("## Steps\n1. **Terminal**: do it.", out.stdout)
        self.assertIn("## Done when\nIt shows ok.", out.stdout)
        self.assertIn("--state all", self.calls()[0])

    def test_show_finds_a_done_item_and_refuses_an_unknown_one(self):
        self.assertEqual(self.wm("show", "alpha/0391/02").returncode, 0)
        gone = self.wm("show", "alpha/0391/09")
        self.assertEqual(gone.returncode, 1)
        self.assertIn("no manual item alpha/0391/09", gone.stderr)
        self.assertEqual(self.wm("show", "nofarm/0391/01").returncode, 1)

    def test_done_runs_manual_done_for_the_items_farm(self):
        out = self.wm("done", "alpha/0391/01")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("manual alpha/0391/01 done", out.stdout)
        self.assertEqual(self.calls(), [f"manual done alpha/0391/01 --repo {self.home / 'a' / 'alpha'}"])

    def test_done_passes_the_cli_failure_on(self):
        (self.stub / "alpha.fail").write_text("error: no manual item alpha/0391/09\n")
        out = self.wm("done", "alpha/0391/09")
        self.assertEqual(out.returncode, 1)
        self.assertIn("no manual item alpha/0391/09", out.stderr)

    def test_bad_ids_and_commands_exit_2_and_call_nothing(self):
        for args in (("show",), ("show", "alpha/391/1"), ("done", "alpha"), ("done", "a", "b"), ("nope",)):
            with self.subTest(args=args):
                self.assertEqual(self.wm(*args).returncode, 2)
        self.assertFalse((self.stub / "calls.log").exists())

    def test_help_prints_the_usage_and_exits_0(self):
        out = self.wm("h")
        self.assertEqual(out.returncode, 0)
        self.assertIn("wm.py list", out.stdout)


if __name__ == "__main__":
    unittest.main()
