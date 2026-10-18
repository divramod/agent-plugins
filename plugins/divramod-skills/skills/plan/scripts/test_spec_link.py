"""spec_link.py and `plan.py new --spec` (hal2 plan 0364, step 5): scratch repositories, the real spec and design
skills beside the plan skill."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PLAN = HERE / "plan.py"
ACTIONS = HERE.parent.parent
SPEC = ACTIONS / "spec" / "scripts" / "spec.py"
DESIGN = ACTIONS / "design" / "scripts" / "design.py"

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
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        self.plans = self.root / "plans"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cmd(self, script, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(script), "--root" if script == PLAN else "--repo",
                               str(self.root), *args], capture_output=True, text=True, cwd=self.root)

    def plan(self, *args) -> dict:
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

    def test_new_spec_writes_the_records_into_the_spec_folder_and_keeps_its_number(self):
        folder = self.new_spec()

        info = self.plan("new", "--spec", folder.name[:4])

        self.assertEqual(info["slug"], folder.name)
        for name in ("plan.md", "decisions.md", "questions.md", "handoff.md", "spec.md"):
            self.assertTrue((folder / name).is_file(), name)
        self.assertEqual(sorted(p.name for p in self.plans.iterdir() if p.is_dir()), [folder.name])
        self.assertEqual((self.plans / "CURRENT_PLAN").read_text(), folder.name + "\n")
        self.assertEqual(info["title"], "Plan %s: login speed" % folder.name[:4])
        self.assertEqual(info["spec"], f"plans/{folder.name}/spec.md")
        self.assertEqual(info["designs"], [])

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
        self.assertNotIn("<seedbag>", text)
        self.assertEqual(info["problems"], [])

    def test_the_goal_comes_from_the_flag_or_else_the_specs_description(self):
        self.new_spec()
        info = self.plan("new", "--spec", "1", "--goal", "Make logging in fast.")
        self.assertIn("Make logging in fast.", (self.plans / info["slug"] / "plan.md").read_text())

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
                             {"spec": f"plans/{folder.name}/spec.md", "designs": []})

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

    def test_it_refuses_a_folder_with_a_plan_and_a_ref_without_a_spec(self):
        self.new_spec()
        self.plan("new", "--spec", "1")

        again = self.run_cmd(PLAN, "new", "--spec", "1")
        self.assertEqual(again.returncode, 1)
        self.assertIn("already has a plan.md", again.stderr)

        none = self.run_cmd(PLAN, "new", "--spec", "77")
        self.assertEqual(none.returncode, 1)
        self.assertIn("no spec matches", none.stderr)

    def test_it_refuses_a_research_or_masterplan_beside_a_spec(self):
        self.new_spec()
        for flag in ("--research", "--masterplan"):
            result = self.run_cmd(PLAN, "new", "--spec", "1", flag)
            self.assertEqual(result.returncode, 1, flag)
            self.assertIn("cannot be combined", result.stderr)
        self.assertFalse((self.plans / "0001-login-speed" / "plan.md").exists())

    def test_new_without_spec_while_current_names_a_spec_only_folder_gives_the_hint(self):
        folder = self.new_spec()

        result = self.run_cmd(PLAN, "new", "something else")

        self.assertEqual(result.returncode, 1)
        self.assertIn(f"names the spec {folder.name}", result.stderr)
        self.assertIn(f"new --spec {folder.name[:4]}", result.stderr)
        self.assertEqual(sorted(p.name for p in self.plans.iterdir() if p.is_dir()), [folder.name])  # no number taken

    def test_no_spec_makes_an_unrelated_plan_and_a_planned_spec_gives_no_hint(self):
        folder = self.new_spec()
        other = self.plan("new", "something else", "--no-spec")
        self.assertEqual(other["slug"], "0002-something-else")

        (self.plans / "CURRENT_PLAN").write_text(folder.name + "\n")
        self.plan("new", "--spec", "1")
        self.assertEqual(self.plan("new", "a third plan")["slug"], "0003-a-third-plan")

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
        self.plan("new", "--spec", "1")

        result = self.run_cmd(PLAN, "check", str(self.plans / "0001-login-speed"))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
