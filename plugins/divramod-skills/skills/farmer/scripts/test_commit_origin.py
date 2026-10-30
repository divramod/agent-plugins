"""The farmer's own commit names its field in a `Worktree:` trailer, none where the farm's commits are neutral (hal2
plan 0409 D15, step 11)."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import commit_origin
import unit_scripts  # noqa: F401  (the skills unit's scripts/ on the import path: git_seed)
import git_seed

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import load  # noqa: E402

kit = load("plan", "neutral_testkit", __file__)


class CommitOriginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.top = self.tmp / "farmer-x"
        self.top.mkdir()
        git_seed.guard(self)
        git_seed.grow(self.tmp, "test_commit_origin.CommitOriginTest",
                      lambda: subprocess.run(["git", "init", "-q", str(self.top)], check=True))
        commit_origin.planread.fresh()

    def test_off_names_the_field(self):
        kit.farm(self.top)
        with kit.env(kit.FakeCli(self.tmp, answer='{"neutral": false, "why": "default"}')):
            commit_origin.planread.fresh()
            self.assertEqual(commit_origin.paragraph(str(self.top)), ["-m", "Worktree: farmer-x"])

    def test_no_farm_asks_no_cli_and_names_the_field(self):
        fake = kit.FakeCli(self.tmp)
        with kit.env(fake):
            commit_origin.planread.fresh()
            self.assertEqual(commit_origin.paragraph(str(self.top)), ["-m", "Worktree: farmer-x"])
        self.assertEqual(fake.calls(), [], "no hal.farm: no process")

    def test_a_neutral_farm_gets_no_trailer(self):
        kit.farm(self.top)
        with kit.env(kit.FakeCli(self.tmp)):
            commit_origin.planread.fresh()
            self.assertEqual(commit_origin.paragraph(str(self.top)), [])


if __name__ == "__main__":
    unittest.main()
