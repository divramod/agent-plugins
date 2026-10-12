import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import migrate
import roles

ROLE = "---\nduties:\n  mtm: \"*/15 * * * *\"\nservant_limit: 2\nnotify: every-round\n---\n"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Repo(unittest.TestCase):
    """Before plan 0143: main `a/hal2` (origin `hal2.git`) with FARMER-ROLE.md, the farmer slot `farmer` on branch
    `farmer` (pushed), state in `skills/farmer/hal2/` and round summaries in `plans/farmer/`; the home is tmp."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.origin, self.main = self.tmp / "hal2.git", self.tmp / "a" / "hal2"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.tmp, "clone", "-q", str(self.origin), str(self.main))
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            git(self.main, "config", k, v)
        (self.main / "FARMER-ROLE.md").write_text(ROLE)
        (self.main / ".gitignore").write_text("plans/CURRENT_PLAN\n")
        git(self.main, "add", ".")
        git(self.main, "commit", "-qm", "init")
        git(self.main, "push", "-q", "origin", "main")
        git(self.main, "remote", "set-head", "origin", "main")
        self.old = self.tmp / ".hal/git/worktree/hal2/farmer"
        self.new = self.old.parent / "farmer-hal2"
        git(self.main, "worktree", "add", "-q", "-b", "farmer", str(self.old))
        git(self.old, "push", "-q", "-u", "origin", "farmer")
        legacy = self.tmp / "skills/farmer"
        (legacy / "hal2/briefs").mkdir(parents=True)
        (legacy / "hal2/log.jsonl").write_text('{"kind": "x"}\n')
        (legacy / "hal2/briefs/b.md").write_text("brief\n")
        (self.main / "plans/farmer/2026-10-06").mkdir(parents=True)
        (self.main / "plans/farmer/.gitignore").write_text("*\n")
        (self.main / "plans/farmer/latest.md").write_text("latest\n")
        (self.main / "plans/farmer/2026-10-06/1000.md").write_text("round\n")
        self.timer = {"label": "local.farmer.hal2", "loaded": False}
        self.agents = []
        for p in (mock.patch.object(Path, "home", return_value=self.tmp),
                  mock.patch.object(roles, "LEGACY", legacy), mock.patch.object(roles, "OVERRIDE", None),
                  mock.patch.object(migrate.timer, "status", lambda name, state: self.timer),
                  mock.patch.object(migrate.deliver, "cli", lambda *a: (0, json.dumps(self.agents)))):
            p.start()
            self.addCleanup(p.stop)

    def migrate(self, dry=False):
        return migrate.Migration(self.main).run(dry)


class Migrate(Repo):
    def test_a_dry_run_lists_the_moves_and_touches_nothing(self):
        code, r = self.migrate(dry=True)
        self.assertEqual(code, 0)
        self.assertEqual(r["new"], str(self.new))
        text = "\n".join(r["steps"])
        for want in ("git worktree move", "git branch -m farmer farmer-hal2", "git push -u origin farmer-hal2",
                     "log.jsonl", "latest.md"):
            self.assertIn(want, text)
        self.assertTrue(self.old.is_dir() and not self.new.exists())
        self.assertTrue((self.tmp / "skills/farmer/hal2/log.jsonl").exists())

    def test_the_slot_branch_role_file_and_state_move_and_a_rerun_does_nothing_more(self):
        code, r = self.migrate()
        self.assertEqual((code, r["problems"]), (0, []))
        self.assertFalse(self.old.exists())
        self.assertEqual(git(self.new, "branch", "--show-current"), "farmer-hal2")
        self.assertEqual(git(self.new, "ls-files", "roles").split(), ["roles/farmer/.gitignore", "roles/farmer/ROLE.md"])
        self.assertFalse((self.new / "FARMER-ROLE.md").exists())
        state = self.new / "roles/farmer"
        self.assertEqual((state / "log.jsonl").read_text(), '{"kind": "x"}\n')
        self.assertTrue((state / "briefs/b.md").exists())
        self.assertEqual((state / "summaries/2026-10-06/1000.md").read_text(), "round\n")
        self.assertTrue((state / "summaries/latest.md").exists())
        self.assertFalse((self.tmp / "skills/farmer/hal2").exists() or (self.main / "plans/farmer").exists())
        self.assertEqual(git(self.new, "status", "--porcelain", "-uall"), "")
        self.assertIn("farmer-hal2", git(self.main, "ls-remote", "--heads", "origin"))
        code, r = self.migrate()
        self.assertEqual(code, 0)
        self.assertEqual(r["steps"], ["git push -u origin farmer-hal2"])

    def test_main_that_moved_the_role_file_brings_the_farmer_branchs_edit_along(self):
        (self.old / "FARMER-ROLE.md").write_text(ROLE + "\n# the user's edit\n")
        git(self.old, "commit", "-qam", "farmer-role: the user's change")
        (self.main / "roles/farmer").mkdir(parents=True)
        git(self.main, "mv", "FARMER-ROLE.md", "roles/farmer/ROLE.md")
        (self.main / "roles/farmer/.gitignore").write_text(roles.GITIGNORE)
        git(self.main, "add", "roles")
        git(self.main, "commit", "-qm", "roles folder")
        git(self.main, "push", "-q", "origin", "main")
        code, r = self.migrate()
        self.assertEqual((code, r["problems"]), (0, []))
        self.assertIn("# the user's edit", (self.new / "roles/farmer/ROLE.md").read_text())
        self.assertFalse((self.new / "FARMER-ROLE.md").exists())

    def test_a_clone_without_origin_head_merges_origin_main(self):
        git(self.main, "remote", "set-head", "origin", "--delete")
        code, r = self.migrate(dry=True)
        self.assertIn(f"merge origin/main into {self.old}", r["steps"])

    def test_an_installed_timer_or_a_session_in_the_slot_refuses_and_moves_nothing(self):
        self.timer = {"label": "local.farmer.hal2", "loaded": True}
        code, r = self.migrate()
        self.assertEqual(code, 1)
        self.assertIn("timer remove", r["problems"][0])
        self.timer = {"label": "local.farmer.hal2", "loaded": False}
        self.agents = [{"checkout": str(self.old), "state": "working", "pane_id": "%1"}]
        code, r = self.migrate()
        self.assertEqual(code, 1)
        self.assertIn("%1", r["problems"][0])
        self.assertTrue(self.old.is_dir() and not self.new.exists())
        self.agents = [{"checkout": str(self.old), "state": "ended", "pane_id": "%1"}]
        self.assertEqual(self.migrate()[0], 0)


if __name__ == "__main__":
    unittest.main()
