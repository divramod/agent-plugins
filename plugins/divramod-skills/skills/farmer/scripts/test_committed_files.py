"""Hal2 plan 0624 step 1: the role folder's .gitignore `!` lines name the files its field may commit; the field
check (`tick.slot_problem`) stops refusing them (the tollman's handoff.md and learnings.md, L247)."""

import tick
from test_farmer import git
from test_wiring import WAGON, WagonRepo

KEEPS = "# the role folder\n*\n!.gitignore\n!ROLE.md\n!handoff.md\n\n!learnings.md\n!*.py\nlog.jsonl\n"


class CommittedFiles(WagonRepo):
    def test_the_bang_lines_become_repo_relative_patterns(self):
        self.assertEqual(WAGON.committed_files(str(self.wm)), ())
        (self.wm / "roles/tollman/.gitignore").write_text(KEEPS)
        self.assertEqual(WAGON.committed_files(str(self.wm)),
                         tuple(f"roles/tollman/{n}" for n in (".gitignore", "ROLE.md", "handoff.md", "learnings.md", "*.py")))

    def test_the_tick_takes_the_committed_role_files_and_still_refuses_strays(self):
        folder = self.wm / "roles/tollman"
        (folder / ".gitignore").write_text(KEEPS)
        (folder / "handoff.md").write_text("handoff\n")
        git(self.wm, "add", "-f", "."), git(self.wm, "commit", "-qm", "the tollman's handoff")
        (folder / "handoff.md").write_text("handoff, changed\n")
        (folder / "learnings.md").write_text("learned\n")
        (folder / "x.py").write_text("x = 1\n")
        self.assertIsNone(tick.slot_problem(str(self.wm), WAGON))
        (self.wm / "stray.txt").write_text("stray\n")
        (self.wm / "roles/farmer").mkdir(exist_ok=True)
        (self.wm / "roles/farmer/ROLE.md").write_text("the farmer's\n")
        (folder / "sub").mkdir()
        (folder / "sub/y.py").write_text("y = 1\n")
        git(self.wm, "add", "-f", "roles/tollman/sub/y.py")  # ignored files show only when staged
        problem = tick.slot_problem(str(self.wm), WAGON)
        self.assertIn("stray.txt", problem)
        self.assertIn("roles/farmer/ROLE.md", problem)
        self.assertIn("roles/tollman/sub/y.py", problem)
        self.assertNotIn("handoff.md", problem)
        self.assertNotIn("learnings.md", problem)
        self.assertNotIn("x.py", problem.replace("y.py", ""))
