"""gp.py where the farm's commits are neutral (hal2 plan 0409 D15, step 11): no plan scope, no Worktree/Plan/Step
trailers, the plan link in the store; off (no farm, or the switch false): what it always did (test_gp.py)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gp_neutral  # noqa: E402
from test_gp import Base, git, run_gp, write  # noqa: E402


def _kit():
    unit = next(p for p in Path(__file__).resolve().parents if (p / ".claude-plugin").is_dir())
    sys.path.insert(0, str(unit / "scripts"))
    try:
        from skillpath import load
    finally:
        sys.path.pop(0)
    return load("plan", "neutral_testkit", __file__)


kit = _kit()


class HeadTest(unittest.TestCase):
    def test_a_plan_scope_is_dropped_any_other_stays(self):
        for subject, want in (("feat(0409|3): x", "feat: x"), ("fix(0391|0409|3)!: x", "fix!: x"),
                              ("docs(0409): x", "docs: x"), ("feat(tool): x", "feat(tool): x"),
                              ("chore: x", "chore: x"), ("feat(plans): 0409 x", "feat(plans): 0409 x")):
            self.assertEqual(gp_neutral.head(subject), want)


class NeutralCommit(Base):
    def setUp(self):
        super().setUp()
        write(self.root, "plans/0364-skills/plan.md")
        write(self.root, "plans/CURRENT_PLAN", "0364-skills\n")
        git(self.root, "add", "plans/0364-skills")
        git(self.root, "commit", "-q", "-m", "docs(plans): plan")
        write(self.root, "code/py/apps/tool/main.py")
        kit.farm(self.root)

    def commit(self, fake, subject, *extra):
        with kit.env(fake):
            return run_gp("--repo", str(self.root), "commit", "--group", "code/py/apps/tool", "--subject", subject,
                          "--json", *extra)

    def test_on_no_plan_scope_no_origin_trailers_and_the_link_before_the_commit(self):
        fake = kit.FakeCli(self.base)
        code, out, err = self.commit(fake, "feat(0364|7): add the tool", "--step", "7/8", "--trailer",
                                     "Co-Authored-By: C <c@example.com>")

        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["subject"], "feat: add the tool")
        self.assertEqual(json.loads(out)["trailers"], ["Co-Authored-By: C <c@example.com>"])
        self.assertEqual(git(self.root, "log", "-1", "--format=%B").strip(),
                         "feat: add the tool\n\nCo-Authored-By: C <c@example.com>")
        self.assertEqual(len(fake.links()), 1)
        self.assertIn("--plan 0364-skills --kind step", fake.links()[0])
        self.assertTrue(fake.links()[0].endswith("--step 7/8 --json"), fake.links()[0])

    def test_on_a_unit_scope_stays(self):
        code, out, _ = self.commit(kit.FakeCli(self.base), "feat(tool): add the tool")

        self.assertEqual((code, json.loads(out)["subject"]), (0, "feat(tool): add the tool"))

    def test_on_the_scan_scopes_by_the_unit_not_the_plan(self):
        with kit.env(kit.FakeCli(self.base)):
            groups = self.scan()["groups"]
        self.assertEqual([g["scope"] for g in groups if g["unit"] == "code/py/apps/tool"], ["tool"])

    def test_off_with_a_farm_everything_as_before(self):
        fake = kit.FakeCli(self.base, '{"neutral": false, "why": "default"}')
        with kit.env(fake):
            self.assertEqual([g["scope"] for g in self.scan()["groups"] if g["unit"] == "code/py/apps/tool"], ["0364"])
        code, out, err = self.commit(fake, "feat(0364|7): add the tool", "--step", "7/8")

        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["subject"], "feat(0364|7): add the tool")
        self.assertEqual(json.loads(out)["trailers"], ["Plan: 0364-skills", "Step: 7/8"])
        self.assertEqual(fake.links(), [])

    def test_a_missing_cli_is_off(self):
        code, out, _ = self.commit(None, "feat(0364|7): add the tool", "--step", "7/8")

        self.assertEqual((code, json.loads(out)["subject"]), (0, "feat(0364|7): add the tool"))


if __name__ == "__main__":
    unittest.main()
