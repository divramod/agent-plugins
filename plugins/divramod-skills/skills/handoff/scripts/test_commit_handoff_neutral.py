"""commit-handoff.sh where the farm's commits are neutral (hal2 plan 0409 D15, step 11): no `Worktree:`/`Plan:`
trailers, a plan scope in the subject dropped, the plan named for the post-commit hook (`planread.py link-next --kind
handoff`); off (no farm, the switch false, no CLI): the trailers as test_commit_handoff.py has them."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import handoff_testkit as kit

SCRIPT = Path(__file__).resolve().parent / "commit-handoff.sh"
ATTRIBUTION = "Co-Authored-By: C <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_1"


def _neutral_kit():
    unit = next(p for p in Path(__file__).resolve().parents if (p / ".claude-plugin").is_dir())
    sys.path.insert(0, str(unit / "scripts"))
    try:
        from skillpath import load
    finally:
        sys.path.pop(0)
    return load("plan", "neutral_testkit", __file__)


nk = _neutral_kit()


class NeutralHandoff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        kit.seed(self.repo, {"code.txt": "v1\n"})
        (self.repo / "plans").mkdir()
        (self.repo / "plans" / "CURRENT_PLAN").write_text("0355-commit-standards\n")
        (self.repo / "INTENT.md").write_text("# Intent\n")
        self.fake_dir = Path(self.tmp.name) / "fake"
        self.fake_dir.mkdir()

    def commit(self, message, farm=True, fake="on"):
        subprocess.run(["git", "config", "--unset", "hal.farm"], cwd=self.repo)
        if farm:
            nk.farm(self.repo)
        env = {**os.environ, **kit.GIT_ENV}
        if fake is not None:
            answer = '{"neutral": true, "why": "setting"}' if fake == "on" else '{"neutral": false, "why": "default"}'
            self.cli = nk.FakeCli(self.fake_dir, answer)
            env["HAL2_CLI_PLANS"] = str(self.cli.path)
        else:
            env["HAL2_CLI_PLANS"] = str(self.fake_dir / "none")
        done = subprocess.run(["bash", str(SCRIPT), message, "INTENT.md"], cwd=self.repo, env=env, text=True,
                              capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return subprocess.run(["git", "log", "-1", "--format=%B"], cwd=self.repo, text=True, capture_output=True,
                              check=True).stdout.rstrip("\n")

    def test_on_no_trailers_no_plan_scope_and_the_link_named(self):
        message = self.commit(f"docs(0355|2): record the decisions\n\n{ATTRIBUTION}")

        self.assertEqual(message, f"docs: record the decisions\n\n{ATTRIBUTION}")
        self.assertEqual(len(self.cli.links()), 1)
        self.assertIn("--plan 0355-commit-standards --kind handoff", self.cli.links()[0])

    def test_on_a_unit_scope_stays_and_a_given_trailer_is_kept(self):
        message = self.commit("docs(plans): note\n\nWorktree: 07")

        self.assertEqual(message, "docs(plans): note\n\nWorktree: 07")

    def test_on_without_a_plan_nothing_is_linked(self):
        (self.repo / "plans" / "CURRENT_PLAN").unlink()

        self.assertEqual(self.commit("docs: note"), "docs: note")
        self.assertEqual(self.cli.links(), [])

    def test_off_the_trailers_as_before(self):
        for farm, fake in ((True, "off"), (False, "on"), (True, None)):
            with self.subTest(farm=farm, fake=fake):
                (self.repo / "INTENT.md").write_text(f"# Intent {farm} {fake}\n")
                message = self.commit(f"docs(plans): record the decisions\n\n{ATTRIBUTION}", farm, fake)
                self.assertEqual(message, "docs(plans): record the decisions\n\n"
                                 f"Worktree: {self.repo.name}\nPlan: 0355-commit-standards\n{ATTRIBUTION}")
                if fake:
                    self.assertEqual(self.cli.links(), [])


if __name__ == "__main__":
    unittest.main()
