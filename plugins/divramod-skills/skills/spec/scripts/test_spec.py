"""spec.py: the spec folder it writes, the plan numbers it shares, show, list and approve (hal2 plan 0364 step 4, D8).

Each test runs in a fresh git repository. The checker tests need `hal2-cli-records` (`$HAL2_CLI_RECORDS`, else on
PATH) and are skipped without it; the plan skill's own test_folder.py proves `plan.py check` on a spec folder.
"""
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
sys.path.insert(0, str(HERE))

import spec  # noqa: E402
import envelope  # noqa: E402  (the plan skill's, put on the path by spec)
import plan_number  # noqa: E402

RECORDS = os.environ.get("HAL2_CLI_RECORDS") or shutil.which("hal2-cli-records")
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


class SpecTest(unittest.TestCase):
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

    def test_new_writes_spec_md_with_the_next_number_and_names_it_current(self):
        info = self.new()
        folder = self.root / "plans" / "0008-login-with-passkeys"
        self.assertEqual(info["slug"], folder.name)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["spec.md"])
        self.assertEqual((self.root / "plans" / "CURRENT_PLAN").read_text(), folder.name + "\n")
        front, body = envelope.split((folder / "spec.md").read_text())
        meta = envelope.parse(front)
        self.assertEqual((meta["type"], meta["id"], meta["status"], meta["title"]),
                         ("Spec", 8, "draft", "Login with passkeys"))
        self.assertIn("# Spec 0008: Login with passkeys", body)
        self.assertEqual(envelope.headings(body, 2), ["Problem", "Users and goals", "Scope", "Requirements",
                                                      "Acceptance criteria", "Open questions", "Design"])
        self.assertIsNone(info["plan"])
        self.assertIsNone(info["design"])

    def test_the_number_is_reserved_and_seen_as_taken(self):
        first, second = self.new(), self.new("Sync status")
        self.assertEqual((first["number"], second["number"]), ("0008", "0009"))
        self.assertIn(8, plan_number.taken(self.root))
        self.assertEqual(plan_number.next_number(self.root, reserve=False), 10)
        self.assertEqual(plan_number.duplicates(self.root), {})

    def test_new_refuses_a_long_title_and_a_slug_that_exists_without_taking_a_number(self):
        self.new()
        reserved = dict(plan_number.reservations(self.root))
        code, _, err = self.run_spec("new", "one two three four five")
        self.assertEqual(code, 1)
        self.assertIn("at most 4 words", err)
        code, _, err = self.run_spec("new", "Login with passkeys")
        self.assertEqual(code, 1)
        self.assertIn("plans/0008-login-with-passkeys already exists", err)
        code, _, err = self.run_spec("new", "Older plan")
        self.assertEqual(code, 1)
        self.assertIn("0007-older-plan", err)
        self.assertEqual(plan_number.reservations(self.root), reserved)

    def test_a_title_with_quotes_stays_valid_front_matter(self):
        info = self.new('The "fast" path')
        self.assertEqual(info["slug"], "0008-the-fast-path")
        meta = envelope.parse(envelope.split((self.root / info["spec"]).read_text())[0])
        self.assertEqual(meta["title"], 'The "fast" path')

    def test_show_resolves_by_number_slug_part_and_current_plan(self):
        self.new()
        self.new("Sync status")
        for ref in ("8", "0008", "0008-login-with-passkeys", "passkeys", "plans/0008-login-with-passkeys/"):
            code, out, err = self.run_spec("show", ref, "--json")
            self.assertEqual((code, json.loads(out)["number"]), (0, "0008"), (ref, err))
        code, out, _ = self.run_spec("show", "--json")
        self.assertEqual(json.loads(out)["slug"], "0009-sync-status")
        self.assertEqual(self.run_spec("show", "nothing")[0], 1)
        self.assertEqual(self.run_spec("show", "7")[0], 1)  # a plan without spec.md is no spec
        (self.root / "plans" / "CURRENT_PLAN").write_text("_skills/9/x\n")
        code, _, err = self.run_spec("show")
        self.assertEqual(code, 1)
        self.assertIn("no spec matches", err)

    def test_show_reports_sections_placeholders_design_and_plan(self):
        info = self.new()
        self.assertEqual(len(info["placeholders"]), 12)
        self.fill(info)
        folder = self.root / info["folder"]
        (folder / "design.html").write_text("<!doctype html>\n")
        (folder / "plan.md").write_text("# Plan 0008: login\n")
        code, out, _ = self.run_spec("show", "8", "--json")
        shown = json.loads(out)
        self.assertEqual((shown["placeholders"], shown["design"], shown["plan"]),
                         ([], f"{info['folder']}/design.html", f"{info['folder']}/plan.md"))
        self.assertIn("passkey sign-up and login", shown["sections"]["Scope"])
        code, out, _ = self.run_spec("show", "8")
        self.assertIn("0008-login-with-passkeys: draft, plans/0008-login-with-passkeys/design.html, plan.md", out)

    def test_a_users_own_angle_brackets_are_no_placeholder(self):
        info = self.new()
        path = self.fill(info)
        path.write_text(path.read_text().replace("- none", "- Is `<plan>` the number or the slug?"))
        self.assertEqual(spec.placeholders(path.read_text()), [])

    def test_approve_refuses_placeholders_then_sets_status_and_date(self):
        info = self.new()
        code, _, err = self.run_spec("approve")
        self.assertEqual(code, 1)
        self.assertIn("12 placeholder(s) left", err)
        self.fill(info)
        code, out, err = self.run_spec("approve", "--json")
        self.assertEqual(code, 0, err)
        approved = json.loads(out)
        self.assertEqual(approved["status"], "approved")
        self.assertRegex(approved["approved"], r"^\d{4}-\d{2}-\d{2}$")

    def test_list_names_every_spec_folder_only(self):
        self.assertEqual(self.run_spec("list")[1], "no spec in plans/\n")
        self.new()
        self.new("Sync status")
        code, out, _ = self.run_spec("list", "--json")
        self.assertEqual([row["slug"] for row in json.loads(out)], ["0008-login-with-passkeys", "0009-sync-status"])

    def test_without_a_repository_it_exits_2(self):
        with tempfile.TemporaryDirectory() as bare, contextlib.chdir(bare):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(spec.main(["list"]), 2)
            self.assertIn("not inside a git repository", err.getvalue())

    @unittest.skipUnless(RECORDS, "hal2-cli-records is not installed and $HAL2_CLI_RECORDS is unset")
    def test_a_spec_only_folder_passes_the_records_checker(self):
        info = self.new()
        folder = self.root / info["folder"]
        (folder / "design.html").write_text("<!doctype html>\n")
        out = subprocess.run([RECORDS, "check", "--json", "--repo", str(self.root)], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(json.loads(out.stdout)["problems"], [])


if __name__ == "__main__":
    unittest.main()
