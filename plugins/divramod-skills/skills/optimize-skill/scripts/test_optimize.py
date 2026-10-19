"""End-to-end tests of optimize.py: the CLI as a subprocess on the fake `claude` (0 tokens), its run home in a temp
folder (`OPTIMIZE_SKILL_HOME`, `OPTIMIZE_SKILL_CLAUDE`)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import fake_claude
import test_loop

CLI = Path(__file__).resolve().parent / "optimize.py"


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.claude = fake_claude.install(self.bin, rules=test_loop.rules(test_loop.WINS), default=test_loop.FAILS)
        self.skill = test_loop.make_skill(self.tmp)
        self.env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.tmp), "TMPDIR": str(self.tmp / "t"),
                    "OPTIMIZE_SKILL_HOME": str(self.home), "OPTIMIZE_SKILL_CLAUDE": self.claude}
        (self.tmp / "t").mkdir()

    def cli(self, *args, code=0):
        child = subprocess.run([sys.executable, str(CLI), *map(str, args)], env=self.env, capture_output=True,
                               text=True, timeout=120)
        self.assertEqual(child.returncode, code, child.stdout + child.stderr)
        return child

    def js(self, *args, code=0):
        return json.loads(self.cli(*args, "--json", code=code).stdout)

    def test_help(self):
        for word in ("h", "help"):
            out = self.cli(word).stdout
            for part in ("optimize.py init <skill-dir>", "estimate", "run", "status", "diff"):
                self.assertIn(part, out)

    def test_init_writes_only_a_missing_evals_json(self):
        (self.skill / "evals" / "evals.json").unlink()
        before = test_loop.tree(self.skill)
        out = self.js("init", self.skill)
        self.assertEqual(out["state"], "written")
        after = test_loop.tree(self.skill)
        self.assertEqual(set(after) - set(before), {"evals/evals.json"})
        self.assertEqual(self.js("init", self.skill)["state"], "skeleton")
        self.assertEqual(test_loop.tree(self.skill), after)  # a second init changes nothing
        self.assertIn("skeleton", self.cli("run", self.skill, code=1).stderr)
        self.assertFalse(self.home.exists() and any(self.home.rglob("ledger.jsonl")))  # no run folder left

    def test_zero_caps_are_refused(self):  # review 7: 0 used to become the default
        for flag in ("--max-tokens", "--max-rollouts"):
            self.assertIn("must be a positive number", self.cli("run", self.skill, flag, "0", code=1).stderr)
        self.assertFalse(self.home.exists() and any(self.home.rglob("ledger.jsonl")))

    def test_init_reports_counts_and_errors(self):
        self.assertEqual(self.js("init", self.skill), {"state": "ready", "path": str(
            (self.skill / "evals" / "evals.json").resolve()), "train": 3, "val": 2})
        (self.skill / "evals" / "evals.json").write_text(json.dumps(test_loop.evals(val=0)), encoding="utf-8")
        out = self.js("init", self.skill, code=1)
        self.assertEqual(out["state"], "invalid")
        self.assertIn("the set has no val eval", out["errors"])
        self.cli("init", self.tmp / "nowhere", code=1)

    def test_estimate(self):
        out = self.js("estimate", self.skill)
        self.assertEqual((out["rollouts"], out["tokens"], out["fits"]), (35, 35 * 60_000 + 3 * 65_000 + 6 * 30_000,
                                                                         True))
        small = self.js("estimate", self.skill, "--epochs", "1", "--candidates", "1", "--max-tokens", "100000")
        self.assertEqual((small["rollouts"], small["fits"]), (10, False))
        self.assertIn("10 rollouts", self.cli("estimate", self.skill, "--epochs", "1", "--candidates", "1").stdout)
        self.assertEqual(fake_claude.calls(self.bin), [])  # no model call

    def test_run_status_diff(self):
        before = test_loop.tree(self.skill)
        report = self.js("run", self.skill, "--candidates", "1", "--model", "haiku", "--optimizer-model", "haiku",
                         "--support", "sub/empty", "--support", f"sub/q.py={self.skill / 'scripts' / 'q.py'}")
        self.assertEqual(test_loop.tree(self.skill), before)
        self.assertEqual((report["state"], report["stop"]["reason"], report["improved"]),
                         ("done", "train_perfect", True))
        run_dir = Path(report["run_dir"])
        self.assertEqual(run_dir.parent, self.home / "demo")
        models = {c["argv"][c["argv"].index("--model") + 1] for c in fake_claude.calls(self.bin)}
        self.assertEqual(models, {"haiku"})
        status = self.cli("status", "demo").stdout
        self.assertIn("val 0.000 -> 1.000", status)
        self.assertIn("stop train_perfect", status)
        self.assertEqual(self.js("status", "--run", run_dir.name)["run_id"], run_dir.name)  # any skill
        self.assertEqual(self.js("status", self.skill)["run_id"], run_dir.name)  # a skill folder works too
        diff = self.cli("diff", "demo").stdout
        self.assertIn("--- a/demo/SKILL.md", diff)
        self.assertIn("+Print its output unchanged.", diff)
        self.assertFalse(self.js("diff", "demo", "--run", run_dir.name)["empty"])

    def test_run_dir_option_and_refusals(self):
        run_dir = self.tmp / "my-run"
        report = self.js("run", self.skill, "--candidates", "1", "--max-tokens", "300000", "--run-dir", run_dir)
        self.assertEqual((report["stop"]["reason"], report["improved"]), ("budget", False))
        self.assertEqual((run_dir / "best.diff").read_text(), "")
        self.cli("run", self.skill, "--run-dir", run_dir, code=1)  # not empty
        self.cli("run", self.skill, "--run-dir", self.skill / "run", code=1)  # inside the skill
        self.assertFalse((self.skill / "run").exists())
        self.assertIn("no run", self.cli("status", "other", code=1).stderr)
        self.cli("diff", "demo", "--run", "nope", code=1)
        self.cli("run", code=2)


if __name__ == "__main__":
    unittest.main()
