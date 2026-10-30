"""The tollman's own commits where the farm's commits are neutral (hal2 plan 0409 D15, step 11): no `Worktree:`/`Plan:`
trailers (origin.py), no empty `-m` paragraph, no field or plan in a merge's or the yard commit's body; off (no farm, or
the switch false): the trailers as test_origin.py, test_generated.py and test_yard_carry.py have them. The subjects stay:
hal2-git's title reads the cars from `Merge branch '<NN>' into ...` and `chore(yard):`, and the unsaved-work proof
(train_wt.OWN_COMMITS) reads `chore(wagon-train|generated|yard)`."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import git_seed
import origin
import yard
from engine_farm import Farm, out
from test_farmer import git
from test_yard import Yard, git as yard_git
import test_generated as tg


def _kit():
    sys.path.insert(0, str(Path(farmer_frame.__file__).resolve().parents[4] / "scripts"))
    try:
        from skillpath import load
    finally:
        sys.path.pop(0)
    return load("plan", "neutral_testkit", __file__)


kit = _kit()
OFF = '{"neutral": false, "why": "default"}'


class OriginNeutral(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        git_seed.guard(self)
        git_seed.grow(self.tmp, "test_neutral_origin.OriginNeutral", lambda: git(self.tmp, "init", "-q", str(self.repo)))

    def test_without_a_root_or_a_farm_the_trailers_are_as_before(self):
        with kit.env(kit.FakeCli(self.tmp)):
            self.assertEqual(origin.trailers(["02"], ["0355-x"]), "Worktree: 02\nPlan: 0355-x")
            self.assertEqual(origin.trailers(["02"], ["0355-x"], self.repo), "Worktree: 02\nPlan: 0355-x")
            self.assertEqual(origin.paragraph(self.repo, ["02"]), ["-m", "Worktree: 02"])

    def test_a_farm_with_the_switch_off_is_as_before(self):
        kit.farm(self.repo)
        with kit.env(kit.FakeCli(self.tmp, OFF)):
            self.assertEqual(origin.paragraph(self.repo, ["02", "03"], ["0355-x"]), ["-m", "Worktree: 02, 03\nPlan: 0355-x"])

    def test_on_there_are_no_trailers_and_no_paragraph(self):
        kit.farm(self.repo)
        with kit.env(kit.FakeCli(self.tmp)):
            self.assertEqual(origin.trailers(["02"], ["0355-x"], self.repo), "")
            self.assertEqual(origin.paragraph(self.repo, ["02"], ["0355-x"]), [])
        with kit.env(None):  # no CLI: off
            self.assertEqual(origin.paragraph(self.repo, ["02"]), ["-m", "Worktree: 02"])


class NeutralYard(Yard):
    def carried(self, cli):
        self.write({"docs/a.md": "changed\n"})
        yard_git(self.field, "config", "hal.farm", "f-test")
        with kit.env(cli):
            commit, carried, why = self.carry()
        self.assertEqual(why, "")
        return yard_git(self.field, "log", "-1", "--format=%B")

    def test_on_the_body_names_no_plan_and_there_are_no_trailers(self):
        message = self.carried(kit.FakeCli(self.tmp))

        self.assertEqual(message.strip(), "chore(yard): 1 file from the yard\n\n"
                         "Brought in from the main checkout, as the train's first car.\n\n- docs/a.md")
        self.assertNotIn("Worktree", message)

    def test_off_with_a_farm_the_trailer_and_the_old_body(self):
        message = self.carried(kit.FakeCli(self.tmp, OFF))

        self.assertIn("(hal2 plan 0294, D15)", message)
        self.assertTrue(message.strip().endswith("Worktree: main"))


class NeutralTrain(Farm):
    def setUp(self):
        super().setUp()
        for name, text in ((".github/hal2-versions.toml", tg.MAP), ("gen.py", tg.GEN),
                           ("plans/0001/uat.md", "# UAT\n"), ("plans/uats.md", tg.uats("0001"))):
            self.commit(self.main, name, text)
        git(self.main, "push", "-q", "origin", "HEAD")
        git(self.main, "config", "hal.farm", "f-test")  # the worktrees share it
        for field, plan in (("07", "0007"), ("13", "0013")):
            self.crop(field, {f"plans/{plan}/uat.md": "# UAT\n", "plans/uats.md": tg.uats("0001", plan)})
        for name, text in {"plans/0009/uat.md": "# UAT\n", "plans/uats.md": tg.uats("0001", "0009")}.items():
            self.commit(self.main, name, text)
        git(self.main, "push", "-q", "origin", "HEAD")

    def formed(self, cli):
        with kit.env(cli):
            self.round()
        merges = out(self.cw, "log", "--merges", "--format=%B%x00").split("\0")
        return out(self.cw, "log", "-1", "--format=%B"), [m.strip() for m in merges if m.strip()]

    def test_on_the_regeneration_and_the_merges_have_no_trailers_and_no_field_in_the_body(self):
        last, merges = self.formed(kit.FakeCli(self.tmp))

        self.assertEqual(out(self.cw, "log", "-1", "--format=%s"), tg.generated.SUBJECT)
        self.assertNotIn("Worktree", last)
        self.assertNotIn("Plan:", last)
        self.assertTrue(last.rstrip("\n").endswith("plans/uats.md"), last)
        self.assertEqual(sorted(merges), [f"Merge branch '07' into {self.carrier()}",
                                          f"Merge branch '13' into {self.carrier()}"])

    def test_off_with_a_farm_the_trailers_and_the_bodies_as_before(self):
        last, merges = self.formed(kit.FakeCli(self.tmp, OFF))

        self.assertTrue(last.strip().endswith("Worktree: 07, 13"), last)
        self.assertTrue(all("wagon train: field" in m and "Worktree: " in m for m in merges), merges)


if __name__ == "__main__":
    unittest.main()
