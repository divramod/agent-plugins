"""Role on `/handoff c` (hal2 plan 0383, D15, D16): a continued foreman or servant loads its role first, by plans/LEAD
and the plan, never by the field's number."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env=ENV)


def hide(checkout, name, text):
    """The pointer `name` only in the checkout's own git dir (a worktree's admin dir), plans/ without it."""
    out = subprocess.run(["git", "-C", str(checkout), "rev-parse", "--absolute-git-dir"], check=True, text=True,
                         capture_output=True)
    file = Path(out.stdout.strip()) / "hal" / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    return file


class SessionRoleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.main = self.base / "app"
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        git(self.main, "commit", "-q", "--allow-empty", "-m", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def field(self, name, plan=False, lead=False) -> Path:
        path = self.base / "worktree" / "app" / name
        git(self.main, "worktree", "add", "-q", "-b", name, str(path))
        (path / "plans").mkdir(exist_ok=True)
        if plan:
            (path / "plans" / "0001-x").mkdir()
            (path / "plans" / "0001-x" / "plan.md").write_text("# Plan 1: x\n")
            (path / "plans" / "CURRENT_PLAN").write_text("0001-x\n")
        if lead:
            (path / "plans" / "LEAD").write_text("05 0001-x 2\n")
        return path

    def run_role(self, root, *flags):
        r = subprocess.run([sys.executable, str(HERE / "session_role.py"), "--repo", str(root), *flags],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_a_field_with_a_plan_and_no_lead_loads_foreman(self):
        self.assertEqual(self.run_role(self.field("05", plan=True)), "/foreman duties")

    def test_a_field_holding_lead_loads_servant(self):
        self.assertEqual(self.run_role(self.field("31", plan=True, lead=True)), "/servant duties")

    def test_pointers_that_sit_only_in_the_git_dir_decide_the_role(self):
        servant = self.field("31")
        hide(servant, "CURRENT_PLAN", "0001-x\n")
        (servant / "plans" / "0001-x").mkdir()
        (servant / "plans" / "0001-x" / "plan.md").write_text("# Plan 1: x\n")
        self.assertEqual(self.run_role(servant), "/foreman duties")
        hide(servant, "LEAD", "05 0001-x 2\n")
        self.assertEqual(self.run_role(servant), "/servant duties")

    def test_the_field_number_decides_nothing(self):
        """D16: a foreman in field 42 is a foreman, a servant marked in field 03 is a servant."""
        self.assertEqual(self.run_role(self.field("42", plan=True)), "/foreman duties")
        self.assertEqual(json.loads(self.run_role(self.field("03", plan=True, lead=True), "--json")),
                         {"role": "servant", "command": "/servant duties"})

    def test_no_plan_no_lead_the_main_checkout_and_other_roles_load_nothing(self):
        self.assertEqual(self.run_role(self.field("06")), "")
        self.assertEqual(self.run_role(self.main), "")  # the steward
        (self.main / "plans").mkdir()
        (self.main / "plans" / "0001-x").mkdir()
        (self.main / "plans" / "0001-x" / "plan.md").write_text("# Plan 1: x\n")
        (self.main / "plans" / "CURRENT_PLAN").write_text("0001-x\n")
        self.assertEqual(self.run_role(self.main), "")
        git(self.main, "worktree", "add", "-q", "-b", "farmer-app", str(self.base / "worktree" / "app" / "farmer-app"))
        farmer = self.base / "worktree" / "app" / "farmer-app"
        (farmer / "plans").mkdir(exist_ok=True)
        (farmer / "plans" / "0001-x").mkdir()
        (farmer / "plans" / "0001-x" / "plan.md").write_text("# Plan 1: x\n")
        (farmer / "plans" / "CURRENT_PLAN").write_text("0001-x\n")
        self.assertEqual(self.run_role(farmer), "")  # /farmer act loads its own
        self.assertEqual(json.loads(self.run_role(self.main, "--json")), {"role": None, "command": None})


if __name__ == "__main__":
    unittest.main()
