"""Tests of runs.py and estimate.py (no model call)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import estimate
import runs


class RunsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_home(self):
        with mock.patch.dict(os.environ, {runs.HOME_ENV: str(self.tmp / "h")}):
            self.assertEqual(runs.home(), self.tmp / "h")
        with mock.patch.dict(os.environ, {runs.HOME_ENV: ""}):
            self.assertEqual(runs.home(), Path("~/.cache/hal2/optimize-skill").expanduser())

    def test_new_runs_are_unique_and_found_in_order(self):
        made = [runs.new_run("demo", self.tmp) for _ in range(3)]
        self.assertEqual(len({m.name for m in made}), 3)
        self.assertEqual(runs.find("demo", root=self.tmp), None)  # no report yet
        for m in made:
            runs.write_json(m / runs.REPORT, {"run_id": m.name})
        other = self.tmp / "zeta" / "20991231T000000Z"  # a later run of another skill
        other.mkdir(parents=True)
        runs.write_json(other / runs.REPORT, {})
        self.assertEqual(runs.runs("demo", self.tmp), made)
        self.assertEqual(runs.find("demo", root=self.tmp), made[-1])
        self.assertEqual(runs.find("demo", made[0].name, self.tmp), made[0])
        self.assertEqual(runs.find(root=self.tmp), other)
        self.assertIsNone(runs.find("demo", "nope", self.tmp))
        self.assertIsNone(runs.find("missing", root=self.tmp))
        self.assertEqual(runs.read_json(made[0] / runs.REPORT), {"run_id": made[0].name})
        self.assertFalse(list(self.tmp.rglob("*.tmp")))

    def test_skill_name_and_diff_target(self):
        skill = self.tmp / "repo" / "skills" / "folder-name"
        skill.mkdir(parents=True)
        self.assertEqual(runs.skill_name(skill), "folder-name")
        (skill / "SKILL.md").write_text("---\nname: front\n---\n# x\n", encoding="utf-8")
        self.assertEqual(runs.skill_name(skill), "front")
        self.assertEqual(runs.diff_target(skill), ("folder-name/SKILL.md", (self.tmp / "repo" / "skills").resolve()))
        (self.tmp / "repo" / ".git").mkdir()
        self.assertEqual(runs.diff_target(skill), ("skills/folder-name/SKILL.md", (self.tmp / "repo").resolve()))
        self.assertTrue(runs.inside(skill / "a" / "b", skill))
        self.assertFalse(runs.inside(self.tmp / "other", skill))


class EstimateTest(unittest.TestCase):
    def test_counts_and_tokens(self):
        est = estimate.estimate(6, 4, epochs=2, candidates=2, max_tokens=2_000_000, max_rollouts=80)
        counts = {row["kind"]: row["count"] for row in est["rows"]}
        self.assertEqual(counts, {"rollout": 50, "reflect": 2, "edit": 4})
        self.assertEqual(est["tokens"], 50 * 60_000 + 2 * 65_000 + 4 * 30_000)
        self.assertFalse(est["fits"])
        self.assertIn("over the caps", estimate.line(est))
        self.assertTrue(estimate.estimate(1, 1, epochs=1, candidates=1)["fits"])


if __name__ == "__main__":
    unittest.main()
