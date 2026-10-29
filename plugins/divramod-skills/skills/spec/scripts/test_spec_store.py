"""The spec and the design skills in a farm whose plans live in its plan store (hal2 plan 0409 step 9): `spec.py new`
numbers the spec by the store and writes it into the farm's edit copy, the model fills that copy, `approve` takes it
in; `design.py` writes a version and the page there; `plan.py new --spec` plans it; no file reaches the tree. Runs
this checkout's debug build of hal2-cli-plans (skipped without; the files home is every other test's)."""

import json
import re
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import spec  # noqa: E402  (puts the plan skill's scripts on the path)
from store_testkit import DEBUG, StoreFarm  # noqa: E402

SPEC = HERE / "spec.py"
DESIGN = HERE.parents[1] / "design" / "scripts" / "design.py"
PLAN = HERE.parents[1] / "plan" / "scripts" / "plan.py"


@unittest.skipUnless(DEBUG, "no hal2-cli-plans with the store home (cargo build -p hal2-cli-plans)")
class SpecInTheStore(StoreFarm, unittest.TestCase):
    def tool(self, script: Path, *args: str) -> dict:
        return json.loads(self.run_ok(sys.executable, str(script), *args))

    def test_a_spec_its_design_and_its_plan_live_only_in_the_store(self):
        made = self.tool(SPEC, "new", "Passkey login", "--json")
        self.assertEqual((made["slug"], made["spec"], made["plan"]),
                         ("0001-passkey-login", "plans/0001-passkey-login/spec.md", None))
        copy = Path(made["dir"])
        self.assertFalse(copy.is_relative_to(self.repo))
        self.assertIn("spec.md", self.rendered("1"))
        self.assertNotIn("plan.md", self.rendered("1"), "a spec folder has no plan.md")
        # the store home keeps the pointer in the git dir (hal2 plan 0409 step 12), plans/ holds none
        self.assertEqual((self.repo / ".git" / "hal" / "CURRENT_PLAN").read_text(), "0001-passkey-login\n")
        self.assertFalse((self.repo / "plans" / "CURRENT_PLAN").exists())
        self.assertIn("0001-passkey-login: draft", self.run_ok(sys.executable, str(SPEC), "list"))

        text = (copy / "spec.md").read_text()
        (copy / "spec.md").write_text(re.sub(r"<(?!!)[a-z][^<>\n]*>", "filled", text))
        approved = self.tool(SPEC, "approve", "1", "--json")
        self.assertEqual((approved["status"], approved["placeholders"]), ("approved", []))
        self.rendered("1")
        self.assertIn("status: approved", (self.tmp / "check" / "0001-passkey-login" / "spec.md").read_text())

        version = self.tool(DESIGN, "new", "login", "gui", "--title", "Login screen", "--json")
        self.assertTrue(Path(version["path"]).is_relative_to(copy))
        (Path(version["path"]) / "screen.html").write_text("<p>login</p>\n")
        self.run_ok(sys.executable, str(DESIGN), "render")
        files = self.rendered("1")
        self.assertIn("design/login/gui/v1/screen.html", files)
        self.assertIn("design.html", files)
        self.assertEqual(self.tool(DESIGN, "list", "--json")["designs"][0]["files"], ["screen.html"])

        planned = self.tool(PLAN, "new", "--spec", "1", "--no-current")
        self.assertEqual(planned["slug"], "0001-passkey-login")
        self.assertIn("plan.md", self.rendered("1"))
        self.assertEqual(self.cli("show", "1")["title"], "Passkey login")
        self.assert_clean()

    def test_a_refused_spec_claims_no_plan_and_a_spec_only_plan_has_its_title(self):
        refused = subprocess.run([sys.executable, str(SPEC), "new", "Passkey login", "--description", "x" * 201,
                                  "--json"], cwd=self.repo, capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0, refused.stdout)
        self.assertEqual(self.cli("list")["plans"], [], "a refused spec new leaves no claimed plan")
        made = self.tool(SPEC, "new", "Passkey login", "--json")
        self.assertEqual(made["slug"], "0001-passkey-login", "the refusal took no number")
        farm = self.git("config", "--get", "hal.farm").strip()
        with sqlite3.connect(self.tmp / "data" / "plans" / f"{farm}.db") as db:  # a spec-only plan has no plan.md
            titles = db.execute("SELECT title FROM plan WHERE deleted = 0").fetchall()
        self.assertEqual(titles, [("Passkey login",)], "a spec-only plan's title, not its slug")
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
