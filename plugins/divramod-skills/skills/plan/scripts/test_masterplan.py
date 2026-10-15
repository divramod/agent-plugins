"""masterplan.py and plan.py on a masterplan (hal2 plan 0275 step 4): the kind, the crop, `new --masterplan`,
`new --parent`, rows that are no steps, `plan.py masterplan` with and without hal2-cli-plans, a servant's field.

No test needs hal2: `$HAL2_CLI_PLANS` names a fake or nothing, `$HAL2_CLI_RECORDS` nothing."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import masterplan
import masterplan_view

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "plan.py"
MASTER = "0001-masterplan-farm-view"
# What `hal2-cli-plans masterplan --json` answers, cut down from the contract's fixture
# (hal2: code/rust/apps/hal2-cli-plans/tests/fixtures/expected/masterplan.json); `test_the_sample_follows_the_contract`.
SAMPLE = {
    "id": 1, "slug": MASTER, "title": "Masterplan farm view", "crop": {"name": "wheat", "glyph": "🌾", "code": "WH"},
    "current_in": [], "plans_done": 1, "plans_total": 3, "steps_done": 5, "steps_total": 12, "plus": True,
    "rows": [
        {"row": "1", "kind": "done", "status": "done", "needs": [], "slug": "0002-tools", "number": 2, "exists": True,
         "title": "Tools", "done": 3, "total": 3, "next": None, "checkout": "main", "current_in": []},
        {"row": "2", "kind": "running", "status": "running", "needs": ["1"], "slug": "0003-view", "number": 3,
         "exists": True, "title": "View", "done": 2, "total": 4,
         "next": {"number": "3", "title": "step 3", "status": "next"}, "checkout": "01", "current_in": ["01"]},
    ],
    "problems": [{"row": "4", "slug": "0002-tools", "kind": "linked_twice", "same_as": "1"}],
}
PLAN = """---
type: Plan
schema: 1
id: {id}
title: "{slug}"
description: "x"
status: {status}
landing: manual
created: 2026-10-13
{keys}---

# Plan {number}: {slug}

## Steps

| # | Step | Needs | Touches | Who | Done when | Status |
|---|---|---|---|---|---|---|
| 1 | one | | | lead | a check | |
"""


def hal2_file(*parts: str) -> Path | None:
    """A file of hal2's checkout around this skill; None in an installed plugin."""
    return next((p / Path(*parts) for p in HERE.parents if (p / Path(*parts)).is_file()), None)


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


class MasterplanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "09"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        self.plans = self.root / "plans"

    def tearDown(self):
        self.tmp.cleanup()

    def run_plan(self, *args, cli: Path | None = None, pre: tuple = ()) -> subprocess.CompletedProcess:
        missing = str(self.base / "no-such-binary")
        env = {**os.environ, masterplan_view.ENV: str(cli or missing), "HAL2_CLI_RECORDS": missing}
        return subprocess.run([sys.executable, str(SCRIPT), *pre, "--root", str(self.root), *args],
                              capture_output=True, text=True, cwd=self.base, env=env)

    def plan(self, *args, **kwargs):
        result = self.run_plan(*args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def refused(self, *args, **kwargs) -> str:
        result = self.run_plan(*args, **kwargs)
        self.assertEqual(result.returncode, 1, result.stdout)
        return result.stderr

    def write(self, slug: str, status: str = "open", keys: str = "", root: Path | None = None) -> Path:
        path = (root or self.root) / "plans" / slug / "plan.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PLAN.format(id=int(slug[:4]), number=slug[:4], slug=slug, status=status, keys=keys))
        return path

    def farm(self) -> Path:
        """A masterplan and one plan of it, made by `new`; the masterplan's plan.md."""
        self.plan("new", "Masterplan farm view", "--masterplan")
        self.plan("new", "tools", "--parent", "1")
        return self.plans / MASTER / "plan.md"

    def fake_cli(self, answer: str, code: int = 0) -> Path:
        """A hal2-cli-plans that prints `answer`, exits `code` and writes its arguments beside itself."""
        cli = self.base / "hal2-cli-plans"
        (self.base / "answer").write_text(answer)
        cli.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{self.base}/args'\ncat '{self.base}/answer'\n"
                       f"exit {code}\n")
        cli.chmod(0o755)
        return cli

    # the kind and the crop

    def test_the_kind_is_the_slugs_marker_and_no_parent(self):
        self.assertTrue(masterplan.is_masterplan("0274-masterplan-halverse-plugin", None))
        self.assertTrue(masterplan.is_masterplan("0001-masterplan", None))
        self.assertFalse(masterplan.is_masterplan("0275-masterplan-tools", 274))  # D34: a plan of masterplan 0274
        for slug in ("0274-masterplans", "0274-the-masterplan", "masterplan-x", "0274-research-masterplan"):
            self.assertFalse(masterplan.has_marker(slug), slug)
        self.assertEqual(masterplan.marked("farm-view"), "masterplan-farm-view")
        self.assertEqual(masterplan.marked("masterplan-farm-view"), "masterplan-farm-view")
        self.assertTrue(masterplan.of(self.write("0274-masterplan-halverse-plugin")))
        self.assertFalse(masterplan.of(self.write("0275-masterplan-tools", keys="parent: 274\n")))

    def test_the_crops_are_the_specs_values(self):
        spec = hal2_file("code", "rust", "libs", "hal2-records", "specs", "plan.toml")
        if spec is None:
            self.skipTest("hal2's specs/plan.toml is not there (an installed plugin)")
        import tomllib
        keys = tomllib.loads(spec.read_text())["keys"]
        self.assertEqual(list(masterplan.CROPS), next(k["values"] for k in keys if k["name"] == "crop"))

    def test_the_crop_is_the_first_no_unfinished_masterplan_of_any_checkout_uses(self):
        self.assertEqual(masterplan.pick_crop(self.root), "wheat")
        first = self.write("0001-masterplan-a", keys="crop: wheat\n")
        self.write("0002-masterplan-b", keys="crop: corn\n")
        self.write("0003-masterplan-c", keys="crop: sunflower\nparent: 1\n")  # a plan of 0001: no masterplan
        self.assertEqual(masterplan.pick_crop(self.root), "sunflower")
        git(self.root, "commit", "-q", "--allow-empty", "-m", "start")
        git(self.root, "worktree", "add", "-q", str(self.base / "30"), "-b", "30")
        self.write("0004-masterplan-d", keys="crop: sunflower\n", root=self.base / "30")
        self.assertEqual(masterplan.pick_crop(self.root), "potato")
        self.write("0002-masterplan-b", "done", "crop: corn\n", self.base / "30")  # one copy done: it is finished
        self.assertEqual(masterplan.pick_crop(self.root), "corn")
        first.write_text(first.read_text().replace("status: open", "status: done"))
        self.assertEqual(masterplan.pick_crop(self.root), "wheat")
        for n, crop in enumerate(masterplan.CROPS, 10):
            self.write(f"00{n}-masterplan-x", keys=f"crop: {crop}\n")
        self.assertEqual(masterplan.pick_crop(self.root), "wheat")  # all twelve in use: the least used, in order

    # new --masterplan, new --parent

    def test_new_masterplan_writes_the_template_with_its_crop(self):
        info = self.plan("new", "Masterplan farm view", "--masterplan", "--goal", "The farm.")
        text = (self.root / info["path"]).read_text()

        self.assertEqual(info["slug"], MASTER)  # a title that starts with the word is not prefixed twice
        self.assertEqual((info["masterplan"], info["crop"], info["parent"], info["row"]), (True, "wheat", None, None))
        self.assertEqual((info["landing"], info["land"], info["total"]), ("manual", "manual", 0))
        self.assertFalse(info["research"])
        for line in ("crop: wheat\n", "landing: manual\n", "## Brief\n", "- Out: <what it leaves alone>\n",
                     "| # | Step | Needs | Touches | Who | Done when | Status |\n"):
            self.assertIn(line, text)
        for column in ("Model", "Effort", "Window", "Size"):
            self.assertNotIn(f"| {column} |", text)
        second = self.plan("new", "one two three four", "--masterplan")  # the marker is no fifth word
        self.assertEqual((second["slug"], second["crop"]), ("0002-masterplan-one-two-three-four", "corn"))
        self.assertTrue(second["current"])
        self.assertNotIn("plan-names-are-short", self.run_plan("check").stdout)

    def test_new_refuses_what_a_masterplan_is_not(self):
        self.write("0001-plain")
        self.assertIn("do not go together", self.refused("new", "x", "--masterplan", "--parent", "1"))
        self.assertIn("do not go together", self.refused("new", "x", "--masterplan", "--research"))
        self.assertIn("0001-plain, which is no masterplan", self.refused("new", "x", "--parent", "1"))
        self.assertIn("plan-names-are-short", self.refused("new", "one two three four five", "--masterplan"))
        self.assertIn("a repository's plans", self.refused(
            "new", "x", "--masterplan", pre=("--global-root", str(self.base / "global"))))
        self.assertEqual(sorted(p.name for p in self.plans.iterdir()), ["0001-plain"])

    def test_new_parent_writes_the_parent_the_context_line_and_the_masterplans_row(self):
        master = self.farm()
        info = self.plan("current")
        text = (self.root / info["path"]).read_text()

        self.assertEqual((info["slug"], info["masterplan"], info["parent"], info["row"]), ("0002-tools", False, 1, "1"))
        self.assertIn("\nparent: 1\n---\n", text)
        context = text[text.index("## Context"):].splitlines()
        self.assertEqual(context[2], f"- [Masterplan 0001](../{MASTER}/plan.md), row 1: this plan is a plan of it, "
                                     "brought in alone.")
        self.assertIn("| 1 | [0002](../0002-tools/plan.md) tools |  |  | lead | plan 0002 is brought in: its plan.md "
                      "on the default branch says `status: done` | draft |\n", master.read_text())
        self.assertEqual(self.plan("new", "view", "--parent", MASTER, "--research")["row"], "2")
        listed = {p["slug"]: (p["masterplan"], p["parent"], p["row"]) for p in self.plan("list")}
        self.assertEqual(listed, {MASTER: (True, None, None), "0002-tools": (False, 1, "1"),
                                  "0003-research-view": (False, 1, "2")})

    def test_a_done_masterplan_is_open_again_with_a_new_plan(self):
        master = self.farm()
        self.assertTrue(self.plan("status", "1", "done", "--plan", "1")["finished"])
        self.assertIn("status: done\n", master.read_text())
        self.plan("new", "view", "--parent", "1")
        self.assertIn("status: open\n", master.read_text())
        self.assertNotIn("finished:", master.read_text())

    # a masterplan's rows are no steps

    def test_a_masterplans_rows_are_not_sized_and_get_no_step_file_prompt_or_uat(self):
        self.farm()
        self.write("0003-masterplan-tools", keys="run: opus high 1m\nparent: 1\n")  # a plan: its open row is sized
        sized = [line for line in self.run_plan("check").stdout.splitlines() if "(plan-steps-sized)" in line]
        self.assertTrue(sized)
        self.assertTrue(all(line.startswith("plans/0003-masterplan-tools/plan.md:") for line in sized), sized)

        info = self.plan("status", "1", "next", "--plan", "1")
        self.assertNotIn("step_file", info)
        self.assertEqual((info["next"]["number"], info["problems"]), ("1", []))
        self.assertFalse((self.plans / MASTER / "steps").exists())
        self.assertEqual([s["number"] for s in self.plan("ready", "--plan", "1", "--json")["ready"]], ["1"])
        for command in (("prompt", "1"), ("uat",)):
            error = self.refused(*command, "--plan", "1")
            self.assertIn("plan 0001 is a masterplan", error)
            self.assertIn("`plan.py use 0002-tools`", error)
            self.assertEqual(len(error.strip().splitlines()), 1)
        self.assertFalse((self.plans / MASTER / "uat.md").exists())
        self.assertIn("no row '7'", self.refused("prompt", "7", "--plan", "1"))

    # plan.py masterplan

    def test_masterplan_without_the_binary_prints_the_own_rows_and_one_line(self):
        self.farm()
        for args in ((), ("--plan", "1"), ("--plan", "0002-tools")):  # the current plan is a plan of it
            result = self.run_plan("masterplan", *args)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            self.assertEqual(lines[0], f"wheat {MASTER}")
            self.assertEqual(lines[1].split(), ["1", "0002-tools", "draft", "needs", "-"])
            self.assertEqual(lines[2:], ["the roll-up (plans and steps done of all) needs hal2-cli-plans: it is not "
                                         "installed"])
        info = self.plan("masterplan", "--json")
        self.assertEqual((info["slug"], info["crop"], info["rollup"]), (MASTER, "wheat", None))
        self.assertEqual(info["rows"], [{"number": "1", "plan": "0002-tools", "label": "tools", "status": "draft",
                                         "needs": []}])
        self.write("0009-plain")
        self.assertIn("0009-plain is no masterplan and no plan of one", self.refused("masterplan", "--plan", "9"))

    def test_masterplan_prints_the_roll_up_of_hal2_cli_plans(self):
        self.farm()
        cli = self.fake_cli(json.dumps(SAMPLE))
        lines = self.run_plan("masterplan", cli=cli).stdout.splitlines()

        self.assertEqual((self.base / "args").read_text().split("\n")[:-1],
                         ["masterplan", MASTER, "--repo", str(self.root.resolve()), "--json"])
        self.assertEqual(lines[0], f"🌾 {MASTER}  1/3 plans  5/12+ steps")
        self.assertEqual(lines[2].split(), ["2", "0003-view", "01", "2/4", "running", "needs", "1"])
        self.assertEqual(lines[3], "problem: row 4 0002-tools linked_twice (as row 1)")
        info = self.plan("masterplan", "--json", cli=cli)
        self.assertEqual((info["rollup"], info["note"]), (SAMPLE, ""))

    def test_a_binary_that_fails_or_knows_no_masterplan_is_the_own_rows_never_an_error(self):
        self.farm()
        for answer, code, why in (("", 2, "the installed one gave none (exit 2)"), ("null\n", 0, "knows no masterplan"),
                                  ("no json", 0, "knows no masterplan")):
            result = self.run_plan("masterplan", cli=self.fake_cli(answer, code))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines()[0], f"wheat {MASTER}")
            self.assertIn(why, result.stdout.splitlines()[-1])
            self.assertIn("needs hal2-cli-plans", result.stdout.splitlines()[-1])

    def test_the_sample_follows_the_contract(self):
        fixture = hal2_file("code", "rust", "apps", "hal2-cli-plans", "tests", "fixtures", "expected",
                            "masterplan.json")
        if fixture is None:
            self.skipTest("hal2's contract fixture is not there (an installed plugin)")
        contract = json.loads(fixture.read_text())
        self.assertEqual(set(SAMPLE), set(contract))
        self.assertEqual(set(SAMPLE["rows"][0]), set(contract["rows"][0]))
        self.assertEqual(set(SAMPLE["crop"]), set(contract["crop"]))
        self.assertEqual(set(SAMPLE["problems"][0]), set(contract["problems"][-1]))

    # a servant's field

    def test_a_servants_field_reads_the_masterplan_and_is_told_what_to_do_instead(self):
        self.farm()
        (self.plans / "CURRENT_PLAN").write_text(MASTER + "\n")
        (self.plans / "LEAD").write_text(f"09 {MASTER} 1\n")

        result = self.run_plan("masterplan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1],
                         "this field is a servant of the foreman in field 09: row 1, plan 0002-tools")
        self.assertEqual(self.plan("masterplan", "--json")["lead"], {"slot": "09", "plan": MASTER, "step": "1"})
        for command in (("new", "x"), ("new", "x", "--parent", "1"), ("status", "1", "done")):
            error = self.refused(*command)
            self.assertIn(f"a servant of the foreman in field 09 (plan {MASTER} row 1)", error)
            self.assertIn("report to the foreman in field 09, who marks the step", error)
            for word in ("stale", "delete"):
                self.assertNotIn(word, error)
        self.assertEqual(sorted(p.name for p in self.plans.iterdir() if p.is_dir()), [MASTER, "0002-tools"])


if __name__ == "__main__":
    unittest.main()
