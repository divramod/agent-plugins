"""spec_link.py and `plan.py new --spec` (hal2 plan 0364, step 5; plan 0502 step 6, D6, D7): a spec is a plan in state
spec from its start, `new --spec` plans it in place; scratch repositories, the real spec and design skills beside the
plan skill."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import field_free
import testkit
HERE = Path(__file__).resolve().parent
PLAN = HERE / "plan.py"
ACTIONS = HERE.parent.parent
SPEC = ACTIONS / "spec" / "scripts" / "spec.py"
DESIGN = ACTIONS / "design" / "scripts" / "design.py"


def records_cli() -> str | None:
    """The branch's hal2-cli-records (`$HAL2_CLI_RECORDS`, else code/rust/target/debug of this checkout), else the
    one on PATH; the tests needing it are skipped without (the spec skill's testkit finds it the same way)."""
    named = os.environ.get("HAL2_CLI_RECORDS")
    if named:
        return named
    for parent in HERE.parents:
        built = parent / "code/rust/target/debug/hal2-cli-records"
        if built.is_file():
            return str(built)
    return shutil.which("hal2-cli-records")


RECORDS = records_cli()

FILLED = """\
## Problem

Logging in is slow.

## Scope

- In: a login page with a password field
- In: a reset link
- Out: single sign-on

## Requirements

- R1: the system SHALL log a user in within one second
- R2: the system SHALL lock an account after five failures
- Constraints: <stack, platforms, budgets and guardrails it must keep>

## Acceptance criteria

| ID | Given | When | Then |
|---|---|---|---|
| A1 | a user | signs in | the home page shows |
| A2 | <a state> | <an action> | <the observable result> |
| A3 | a locked user | signs in | an error shows |
"""


@unittest.skipUnless(SPEC.is_file() and DESIGN.is_file(),
                     "needs the spec and design skills beside this one (not in the field-independence copy)")
class SpecLinkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        testkit.init_repo(self.root)
        self.plans = self.root / "plans"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cmd(self, script, *args) -> subprocess.CompletedProcess:
        if script == SPEC:
            return testkit.run_spec(self.root, *args)
        return testkit.run(script, ["--root" if script == PLAN else "--repo", str(self.root), *args], cwd=self.root)

    def plan(self, *args) -> dict:
        field_free.free(self.root, args)
        result = self.run_cmd(PLAN, *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def new_spec(self, title="login speed", body=FILLED) -> Path:
        result = self.run_cmd(SPEC, "new", title, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        folder = self.root / json.loads(result.stdout)["folder"]
        text = (folder / "spec.md").read_text()
        head = text[:text.index("## Problem")]
        (folder / "spec.md").write_text(head + body)
        return folder

    def accept(self, folder: Path, feat: str, kind: str, n: int) -> None:
        """A design version as the design skill stores it, accepted in the review state."""
        result = subprocess.run([sys.executable, str(DESIGN), "new", feat, kind, "--repo", str(self.root),
                                 "--plan", folder.name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = folder / "design" / "state.json"
        data = json.loads(state.read_text()) if state.is_file() else {"schema": 1, "designs": {}}
        data["designs"][f"{feat}/{kind}/v{n}"] = {"accepted": True, "comments": []}
        state.write_text(json.dumps(data))

    def front(self, folder: Path, key: str) -> str:
        line = next((l for l in (folder / "plan.md").read_text().split("---")[1].splitlines()
                     if l.startswith(key + ":")), "")
        return line.split(":", 1)[1].strip()

    def test_a_spec_is_a_plan_in_state_spec_before_it_is_planned(self):
        folder = self.new_spec()

        self.assertEqual(self.front(folder, "status"), "spec")
        self.assertNotIn("## Steps", (folder / "plan.md").read_text())
        self.assertEqual((self.plans / "CURRENT_PLAN").read_text(), folder.name + "\n")

    def test_new_spec_plans_the_spec_folders_own_plan_in_place_and_keeps_its_number(self):
        folder = self.new_spec()
        (folder / "decisions.md").write_text((folder / "decisions.md").read_text() + "\nD1 settled in the spec.\n")
        before = (folder / "plan.md").read_text()

        info = self.plan("new", "--spec", folder.name[:4])

        self.assertEqual(info["slug"], folder.name)
        for name in ("plan.md", "decisions.md", "questions.md", "handoff.md", "spec.md"):
            self.assertTrue((folder / name).is_file(), name)
        self.assertEqual(sorted(p.name for p in self.plans.iterdir() if p.is_dir()), [folder.name])
        self.assertEqual((self.plans / "CURRENT_PLAN").read_text(), folder.name + "\n")
        self.assertEqual(self.front(folder, "status"), "open")
        self.assertEqual(self.front(folder, "id"), before.split("id:")[1].split("\n")[0].strip())
        self.assertEqual(self.front(folder, "created"), before.split("created:")[1].split("\n")[0].strip())
        self.assertRegex(self.front(folder, "run"), r"\S+ \S+ \S+")
        self.assertIn("D1 settled in the spec.", (folder / "decisions.md").read_text())  # the ledgers stay
        self.assertEqual(info["title"], "Plan %s: login speed" % folder.name[:4])
        self.assertEqual(info["total"], 2)
        self.assertEqual(info["spec"], f"plans/{folder.name}/spec.md")
        self.assertEqual(info["designs"], [])
        self.assertEqual(info["spec_review"], 0)

    def test_planning_keeps_the_grilled_stamp_and_a_manual_landing_flag(self):
        folder = self.new_spec()
        self.assertEqual(self.run_cmd(SPEC, "grilled", "1", "--how", "autogrill x1").returncode, 0)

        info = self.plan("new", "--spec", "1", "--manual-landing")

        self.assertEqual(info["autogrill_rounds"], 1)
        self.assertEqual(info["landing"], "manual")
        self.assertIn("autogrill", self.front(folder, "grilled"))

    def test_the_brief_is_seeded_from_the_spec_and_the_context_links_it(self):
        folder = self.new_spec()

        info = self.plan("new", "--spec", "login-speed")

        brief = info["brief"]
        self.assertEqual(brief["In"], "a login page with a password field a reset link")
        self.assertEqual(brief["Out"], "single sign-on")
        self.assertIn("R1: the system SHALL log a user in within one second", brief["Must"])
        self.assertIn("R2: the system SHALL lock an account after five failures", brief["Must"])
        self.assertNotIn("Constraints", brief["Must"])  # a placeholder line is no content
        self.assertIn("acceptance criteria A1, A3 of spec.md hold", brief["Proof"])
        self.assertNotIn("A2", brief["Proof"])
        text = (folder / "plan.md").read_text()
        self.assertIn("- Spec: [spec.md](spec.md)\n", text)
        self.assertEqual(text.count("- Spec: "), 1)  # the spec-state line is replaced, not kept
        self.assertNotIn("not written yet", text)
        self.assertNotIn("no steps yet", text)
        self.assertNotIn("<seedbag>", text)
        self.assertIn("## Steps", text)
        self.assertIn("## Notes", text)

    def test_the_goal_comes_from_the_flag_or_else_the_specs_description(self):
        folder = self.new_spec()
        before = (folder / "plan.md").read_text()
        goal = before.split("## Goal\n\n")[1].split("\n\n## Brief")[0]
        self.plan("new", "--spec", "1")
        self.assertIn(f"## Goal\n\n{goal}\n\n## Brief", (folder / "plan.md").read_text())

    def test_the_goal_flag_replaces_the_goal(self):
        folder = self.new_spec()
        self.plan("new", "--spec", "1", "--goal", "Make logging in fast.")
        self.assertIn("## Goal\n\nMake logging in fast.\n\n## Brief", (folder / "plan.md").read_text())

    def test_accepted_designs_become_a_must_line_the_proof_and_the_context_link(self):
        folder = self.new_spec()
        self.accept(folder, "login", "gui", 1)
        self.accept(folder, "login", "erd", 1)
        subprocess.run([sys.executable, str(DESIGN), "render", "--repo", str(self.root), "--plan", folder.name],
                       capture_output=True, check=True)

        info = self.plan("new", "--spec", folder.name)

        self.assertEqual([d["id"] for d in info["designs"]], ["login/gui/v1", "login/erd/v1"])
        self.assertIn("conforms to the accepted designs: login/gui/v1, login/erd/v1 (design.html)",
                      info["brief"]["Must"])
        self.assertIn("the result conforms to the accepted designs", info["brief"]["Proof"])
        self.assertIn("- Spec: [spec.md](spec.md), its designs: [design.html](design.html)\n",
                      (folder / "plan.md").read_text())

    def test_a_design_that_is_not_accepted_is_not_in_the_plan(self):
        folder = self.new_spec()
        subprocess.run([sys.executable, str(DESIGN), "new", "login", "gui", "--repo", str(self.root), "--plan",
                        folder.name], capture_output=True, check=True)

        info = self.plan("new", "--spec", "1")

        self.assertEqual(info["designs"], [])
        self.assertNotIn("conforms", info["brief"]["Must"])

    def test_current_spawns_no_design_process_while_no_review_state_exists(self):
        folder = self.new_spec()
        subprocess.run([sys.executable, str(DESIGN), "new", "login", "gui", "--repo", str(self.root), "--plan",
                        folder.name], capture_output=True, check=True)
        self.assertTrue((folder / "design").is_dir())
        self.assertFalse((folder / "design" / "state.json").exists())
        self.plan("new", "--spec", "1")
        sys.path.insert(0, str(HERE))
        import spec_link
        with mock.patch.object(spec_link.subprocess, "run", side_effect=AssertionError("design.py was spawned")):
            self.assertEqual(spec_link.accepted(self.root, folder), [])
            self.assertEqual(spec_link.fields(self.root, folder / "plan.md"),
                             {"spec": f"plans/{folder.name}/spec.md", "designs": [], "spec_review": 0})

    def test_a_spec_with_placeholders_keeps_the_template_text_and_warns(self):
        folder = self.new_spec(body=FILLED.replace("A3 | a locked user | signs in | an error shows",
                                                   "A3 | <a state> | <an action> | <the result>"))
        text = (folder / "spec.md").read_text()
        (folder / "spec.md").write_text(text.replace("- Out: single sign-on", "- Out: <what it leaves out>"))

        result = self.run_cmd(PLAN, "new", "--spec", "1")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("warning", result.stderr)
        self.assertIn("not approved", result.stderr)
        brief = json.loads(result.stdout)["brief"]
        self.assertEqual(brief["Out"], "")  # still the placeholder: plan check reports it
        self.assertIn("A1 of spec.md", brief["Proof"])

    def test_it_refuses_a_plan_that_is_planned_already_and_a_ref_without_a_spec(self):
        folder = self.new_spec()
        self.plan("new", "--spec", "1")
        planned = (folder / "plan.md").read_text()

        again = self.run_cmd(PLAN, "new", "--spec", "1")
        self.assertEqual(again.returncode, 1)
        self.assertIn("already planned", again.stderr)
        self.assertIn("plan.py use 0001", again.stderr)
        self.assertEqual((folder / "plan.md").read_text(), planned)  # nothing written twice

        none = self.run_cmd(PLAN, "new", "--spec", "77")
        self.assertEqual(none.returncode, 1)
        self.assertIn("no spec matches", none.stderr)

    def test_it_refuses_a_research_a_masterplan_a_parent_and_schema_2_beside_a_spec(self):
        folder = self.new_spec()
        for flag in ("--research", "--masterplan", "--parent=1"):
            result = self.run_cmd(PLAN, "new", "--spec", "1", flag)
            self.assertEqual(result.returncode, 1, flag)
            self.assertIn("cannot be combined", result.stderr)
        schema = self.run_cmd(PLAN, "new", "--spec", "1", "--schema", "2")
        self.assertEqual(schema.returncode, 1)
        self.assertIn("schema 1", schema.stderr)
        self.assertEqual(self.front(folder, "status"), "spec")  # still the spec

    def test_a_seed_is_allowed_beside_a_spec_and_replaces_the_seed_line(self):
        folder = self.new_spec()
        fake = Path(self.tmp.name) / "fake-shooter"
        fake.write_text("#!/bin/sh\ncase \"$2\" in list-open) printf '%s\\n' '"
                        + json.dumps({"shotfiles": "/x", "shots": [{"id": 1, "file": "skill-spec", "number": "4",
                                                                    "title": "spec loop", "body": "b"}]})
                        + "';; mark-sent) echo '{}';; esac\n")
        fake.chmod(0o755)
        env = {**os.environ, "HAL2_CLI_SHOOTER": str(fake)}
        field_free.free(self.root, ["new"])

        result = testkit.run(PLAN, ["--root", str(self.root), "new", "--spec", "1", "--seed", "skill-spec#4"],
                             env=env, cwd=self.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        text = (folder / "plan.md").read_text()
        self.assertEqual(text.count("- Seed: "), 1)
        self.assertIn("skill-spec#4", text)
        self.assertTrue(json.loads(result.stdout)["seed"]["marked"])

    def test_new_without_spec_while_current_names_a_spec_gives_the_in_place_hint(self):
        folder = self.new_spec()

        result = self.run_cmd(PLAN, "new", "something else")

        self.assertEqual(result.returncode, 1)
        self.assertIn(f"names the spec {folder.name}", result.stderr)
        self.assertIn("in place", result.stderr)
        self.assertIn(f"new --spec {folder.name[:4]}", result.stderr)
        self.assertEqual(sorted(p.name for p in self.plans.iterdir() if p.is_dir()), [folder.name])  # no number taken

    def test_a_legacy_spec_folder_without_a_plan_still_gets_one_written_into_it(self):
        folder = self.new_spec()
        for name in ("plan.md", "decisions.md", "questions.md", "handoff.md"):
            (folder / name).unlink()  # a spec of before plan 0502: spec.md alone

        self.assertIn("names the spec", self.run_cmd(PLAN, "new", "x").stderr)
        info = self.plan("new", "--spec", "1")

        self.assertEqual(info["slug"], folder.name)
        self.assertEqual(self.front(folder, "status"), "open")
        self.assertTrue((folder / "decisions.md").is_file())
        self.assertEqual(sorted(p.name for p in self.plans.iterdir() if p.is_dir()), [folder.name])

    def test_no_spec_makes_an_unrelated_plan_and_a_planned_spec_gives_no_hint(self):
        folder = self.new_spec()
        other = self.plan("new", "something else", "--no-spec")
        self.assertEqual(other["slug"], "0002-something-else")

        (self.plans / "CURRENT_PLAN").write_text(folder.name + "\n")
        self.plan("new", "--spec", "1")
        self.assertEqual(self.plan("new", "a third plan")["slug"], "0003-a-third-plan")

    def test_a_plan_without_a_spec_is_made_as_before(self):
        info = self.plan("new", "plain feature", "--goal", "Do it.")

        self.assertEqual(info["slug"], "0001-plain-feature")
        current = self.plan("current")
        self.assertEqual((current["spec"], current["designs"], current["spec_review"]), ("", [], 0))
        text = (self.plans / info["slug"] / "plan.md").read_text()
        self.assertEqual(self.front(self.plans / info["slug"], "status"), "open")
        self.assertIn("## Goal\n\nDo it.", text)
        self.assertIn("- In: <what this plan delivers>", text)
        self.assertIn("| 1 | <step> |", text)
        self.assertNotIn("spec_review", text)
        self.assertEqual(sorted(p.name for p in (self.plans / info["slug"]).iterdir()),
                         ["decisions.md", "handoff.md", "plan.md", "questions.md"])

    def test_new_needs_a_title_or_a_spec(self):
        result = self.run_cmd(PLAN, "new")
        self.assertEqual(result.returncode, 1)
        self.assertIn("needs a title", result.stderr)

    def test_current_shows_spec_and_designs_of_a_plan_made_from_a_spec_and_empty_ones_otherwise(self):
        folder = self.new_spec()
        self.accept(folder, "login", "gui", 1)
        self.plan("new", "--spec", "1")

        current = self.plan("current")
        self.assertEqual(current["spec"], f"plans/{folder.name}/spec.md")
        self.assertEqual([d["id"] for d in current["designs"]], ["login/gui/v1"])
        self.assertEqual(current["designs"][0]["kind"], "gui")

        plain = self.plan("new", "no spec here", "--no-spec")
        self.assertEqual(self.plan("current")["slug"], plain["slug"])
        self.assertEqual(self.plan("current")["spec"], "")
        self.assertEqual(self.plan("current")["designs"], [])

    def test_the_plan_made_from_a_spec_passes_the_plan_check(self):
        self.new_spec()
        self.plan("new", "--spec", "1", "--schema", "1")

        result = self.run_cmd(PLAN, "check", str(self.plans / "0001-login-speed"))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(RECORDS, "needs the branch's hal2-cli-records (spec-state plans, step 1)")
    def test_the_records_checker_accepts_the_spec_state_plan_and_the_planned_one(self):
        folder = self.new_spec()
        env = {**os.environ, "HAL2_CLI_RECORDS": RECORDS}
        checked = lambda: testkit.run(PLAN, ["--root", str(self.root), "check", str(folder)], env=env, cwd=self.root)

        self.assertEqual(checked().returncode, 0, checked().stdout)
        self.plan("new", "--spec", "1")
        result = checked()
        # the planned plan still holds the template's placeholder step: only that is reported, never the shape
        self.assertNotIn("(plan-spec", result.stdout)
        self.assertNotIn("unknown key", result.stdout)


if __name__ == "__main__":
    unittest.main()
