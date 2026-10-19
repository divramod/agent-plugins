"""Tests of loop.py on the fake `claude` (never the real one, 0 tokens), with the plan's regressions:
(a) the token cap stops a run mid-epoch, (b) the skill's folder is never written, (c) a tie is rejected,
(d) validation tasks never reach a reflection or edit prompt."""

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import fake_claude
import loop

SKILL = "---\nname: demo\ndescription: d\n---\n\n# demo\n\nRun `python3 q.py`.\nPrint its output.\n"
EDIT_SET = [{"op": "replace", "anchor": "Print its output.", "text": "Print its output unchanged."}]
REFLECTION = "The skill lets the agent summarize; it must print the output unchanged."
CALL = 84966  # fake_claude.USAGE's total


def evals(train=3, val=2):
    def item(ident, split, n):
        return {"id": ident, "prompt": f"{split.upper()}-TASK-{n}: show the open questions", "split": split,
                "files": [], "checks": [{"op": "contains", "value": "Q1"}]}
    return {"skill_name": "demo", "evals": [item(f"t{n}", "train", n) for n in range(1, train + 1)]
            + [item(f"v{n}", "val", n) for n in range(1, val + 1)]}


def tree(folder):
    """{relative path: sha256} of every file under folder."""
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def rules(pass_rule=None):
    """Reflection and edit replies, then `pass_rule` (a rollout that passes), else the failing default."""
    fenced = f"```json\n{json.dumps(EDIT_SET)}\n```"
    out = [{"prompt": "## Failed train rollouts", "stream": fake_claude.stream_for(text=REFLECTION)},
           {"prompt": "## Edit set schema", "stream": fake_claude.stream_for(text=fenced)}]
    return out + ([pass_rule] if pass_rule else [])


WINS = {"skill": "unchanged", "stream": fake_claude.stream_for(text="Q1: open")}
TRAIN_ONLY = {"skill": "unchanged", "prompt": "TRAIN-TASK", "stream": fake_claude.stream_for(text="Q1: open")}
FAILS = {"stream": fake_claude.stream_for(text="no questions")}


def make_skill(root, data=None, skill_md=SKILL):
    skill = Path(root) / "skills" / "demo"
    (skill / "evals").mkdir(parents=True)
    (skill / "scripts").mkdir()
    (skill / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (skill / "scripts" / "q.py").write_text("print('Q1')\n", encoding="utf-8")
    (skill / "evals" / "evals.json").write_text(json.dumps(evals() if data is None else data), encoding="utf-8")
    return skill


class LoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.skill = make_skill(self.tmp)
        self.env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.tmp), "ANTHROPIC_API_KEY": "k"}

    def go(self, pass_rule=None, default=FAILS, **settings):
        claude = fake_claude.install(self.bin, rules=rules(pass_rule), default=default)
        settings.setdefault("candidates", 1)
        self.run_dir = self.tmp / "home" / "demo" / "r1"
        job = loop.Run(self.skill, self.run_dir, settings, workspace=self.tmp / "ws", claude=claude, env=self.env)
        return job.run()

    def llm_prompts(self):
        return [c["prompt"] for c in fake_claude.calls(self.bin) if "--safe-mode" in c["argv"]]

    def test_a_winning_candidate(self):
        report = self.go(WINS)
        self.assertEqual(report["baseline"], {"train": 0.0, "val": 0.0})
        self.assertEqual(report["best"], {"train": 1.0, "val": 1.0, "candidate": "e1c1"})
        self.assertTrue(report["improved"])
        self.assertEqual(report["stop"]["reason"], "train_perfect")
        self.assertEqual(report["epochs"][0]["winner"], "e1c1")
        self.assertEqual(report["tokens"]["rollouts"], 10)
        self.assertEqual(report["tokens"]["spent"], 12 * CALL)  # 10 rollouts, a reflection, an edit set
        self.assertEqual(json.loads((self.run_dir / "report.json").read_text())["state"], "done")
        self.assertIn("+Print its output unchanged.", (self.run_dir / "best.diff").read_text())
        self.assertFalse((self.tmp / "ws").exists())  # the workspace goes at the end
        for name in ("SKILL.md", "scores.json", "rollouts.jsonl", "edits.json"):
            self.assertTrue((self.run_dir / "candidates" / "e1c1" / name).is_file(), name)

    def test_best_diff_applies(self):
        self.go(WINS)
        copy = self.tmp / "copy"
        (copy / "demo").mkdir(parents=True)
        (copy / "demo" / "SKILL.md").write_text(SKILL, encoding="utf-8")
        subprocess.run(["git", "apply", str(self.run_dir / "best.diff")], cwd=copy, check=True)
        self.assertIn("Print its output unchanged.", (copy / "demo" / "SKILL.md").read_text())

    def test_regression_a_cap_stops_mid_epoch(self):
        # baseline 5 rollouts (425k) + reflection + edit set = 595k; the next rollout's 85k would pass 600k
        report = self.go(WINS, max_tokens=600_000)
        self.assertEqual(report["stop"]["reason"], "budget")
        self.assertIn("token cap", report["stop"]["detail"])
        self.assertEqual(len(report["epochs"]), 1)
        self.assertFalse(report["improved"])
        self.assertEqual((self.run_dir / "best.diff").read_text(), "")
        self.assertEqual(len(fake_claude.calls(self.bin)), 7)
        self.assertLessEqual(report["tokens"]["spent"], 600_000)

    def test_regression_cap_keeps_an_accepted_winner(self):  # review 1
        # baseline 5 + reflection + edit + e1c1's 5 rollouts = 12 calls (1,019,592); e1c2's edit (30k) would pass
        report = self.go(WINS, candidates=2, max_tokens=1_040_000)
        self.assertEqual(report["stop"]["reason"], "budget")
        self.assertTrue(report["improved"])
        self.assertEqual(report["best"], {"train": 1.0, "val": 1.0, "candidate": "e1c1"})
        self.assertEqual(report["epochs"][0]["winner"], "e1c1")
        self.assertIn("+Print its output unchanged.", (self.run_dir / "best.diff").read_text())
        self.assertEqual(json.loads((self.run_dir / "report.json").read_text())["best"]["candidate"], "e1c1")

    def test_accepted_loser_goes_to_rejected(self):  # review 8
        second = [{"op": "replace", "anchor": "Print its output.", "text": "Print its output, unchanged."}]
        extra = {"prompt": "Already proposed this round", "stream": fake_claude.stream_for(text=json.dumps(second))}
        claude = fake_claude.install(self.bin, rules=[extra] + rules(WINS), default=FAILS)
        self.run_dir = self.tmp / "r5"
        report = loop.Run(self.skill, self.run_dir, {"candidates": 2}, workspace=self.tmp / "ws", claude=claude,
                          env=self.env).run()
        self.assertEqual([c["accepted"] for c in report["epochs"][0]["candidates"]], [True, True])
        self.assertEqual(report["epochs"][0]["winner"], "e1c1")
        [lost] = [json.loads(line) for line in (self.run_dir / "rejected.jsonl").read_text().splitlines()]
        self.assertEqual((lost["candidate"], lost["reason"], lost["margin"], lost["gate_margin"]),
                         ("e1c2", "lost to e1c1", 0.0, 1.0))
        self.assertEqual(lost["edits"], second)

    def test_regression_cut_off_rollouts_are_charged_the_estimate(self):  # review 2
        cut = {"stream": [{"type": "assistant", "message": {"id": "m", "content": [], "usage": {"input_tokens": 900,
                          "output_tokens": 100}}}], "exit": 1}
        report = self.go(default=cut, epochs=1)
        lines = [json.loads(line) for line in (self.run_dir / "ledger.jsonl").read_text().splitlines()]
        rollouts = [line for line in lines if line["kind"] == "rollout"]
        self.assertTrue(rollouts)
        self.assertTrue(all(line["tokens"] == 60_000 and line["floored"] for line in rollouts))
        self.assertTrue(all(line["input"] == 900 for line in rollouts))  # the exact part is kept beside the floor
        self.assertGreaterEqual(report["tokens"]["spent"], 60_000 * len(rollouts))

    def test_regression_no_leftovers(self):  # review 4: no llm folder, no ~/.claude/projects folder of the run
        config = self.tmp / "config"
        self.env.update(CLAUDE_CONFIG_DIR=str(config), FAKE_CLAUDE_PROJECTS="1")
        import projects
        mine = config / "projects" / projects.slug((self.tmp / "ws").resolve())
        (mine / "memory").mkdir(parents=True)  # the user had this one: kept
        (config / "projects" / "other" / "memory").mkdir(parents=True)
        report = self.go(WINS)
        llm_cwds = {c["cwd"] for c in fake_claude.calls(self.bin) if "--safe-mode" in c["argv"]}
        self.assertEqual(llm_cwds, {str((self.tmp / "ws-llm").resolve())})
        self.assertFalse((self.tmp / "ws").exists() or (self.tmp / "ws-llm").exists())
        self.assertEqual(sorted(p.name for p in (config / "projects").iterdir()), sorted([mine.name, "other"]))
        self.assertEqual(len(report["removed"]), 1)

    def test_projects_remove_keeps_content(self):
        import projects
        root = self.tmp / "p"
        for name, files in (("empty", []), ("mem", ["memory/MEMORY.md"]), ("log", ["x.jsonl"])):
            (root / name / "memory").mkdir(parents=True)
            for rel in files:
                (root / name / rel).write_text("x", encoding="utf-8")
        removed = projects.remove([root / "empty", root / "mem", root / "log", root / "absent"])
        self.assertEqual(removed, [str(root / "empty")])
        self.assertEqual(sorted(p.name for p in root.iterdir()), ["log", "mem"])

    def test_regression_zero_caps_are_refused(self):  # review 7
        with self.assertRaisesRegex(loop.RunError, "max_tokens must be a positive number"):
            loop.Run(self.skill, self.tmp / "r6", {"max_tokens": 0})
        self.assertFalse((self.tmp / "r6").exists())

    def test_rollout_cap_stops(self):
        report = self.go(WINS, max_rollouts=7)
        self.assertEqual(report["stop"]["reason"], "budget")
        self.assertEqual(report["tokens"]["rollouts"], 7)

    def test_regression_b_skill_folder_never_written(self):
        before = tree(self.skill)
        report = self.go(WINS, candidates=2)
        self.assertTrue(report["improved"])
        self.assertEqual(tree(self.skill), before)
        self.assertEqual(sorted(p.name for p in self.skill.rglob("*")), ["SKILL.md", "evals", "evals.json",
                                                                           "q.py", "scripts"])

    def test_folders_inside_the_skill_are_refused(self):
        with self.assertRaises(loop.RunError):
            loop.Run(self.skill, self.skill / "run", {})
        with self.assertRaises(loop.RunError):
            loop.Run(self.skill, self.tmp / "run", {}, workspace=self.skill / "evals" / "ws")
        self.assertFalse((self.skill / "run").exists())

    def test_regression_c_a_tie_is_rejected(self):
        report = self.go(TRAIN_ONLY, epochs=3)  # the candidate passes train, ties on val
        first = report["epochs"][0]["candidates"][0]
        self.assertEqual((first["train"], first["val"], first["margin"], first["accepted"]), (1.0, 0.0, 0.0, False))
        self.assertIn("tie", first["gate"])
        self.assertEqual(report["stop"]["reason"], "two_rejected")
        self.assertEqual(len(report["epochs"]), 2)
        self.assertFalse(report["improved"])
        self.assertEqual(report["best"]["candidate"], "c0")
        self.assertEqual((self.run_dir / "best.diff").read_text(), "")
        rejected = [json.loads(line) for line in (self.run_dir / "rejected.jsonl").read_text().splitlines()]
        self.assertEqual([r["margin"] for r in rejected], [0.0, 0.0])
        self.assertIn("Rejected edit sets", self.llm_prompts()[-1])  # epoch 2's edit prompt is told

    def test_regression_d_val_tasks_never_reach_the_optimizer(self):
        for rule in (WINS, TRAIN_ONLY):
            with self.subTest(rule=rule.get("prompt")):
                self.setUp()
                self.go(rule, epochs=2, candidates=2)
                prompts = self.llm_prompts()
                self.assertTrue(prompts)
                self.assertTrue(any("TRAIN-TASK" in p for p in prompts))
                self.assertFalse([p for p in prompts if "VAL-TASK" in p or "v1" in p.split()])
                rollouts = [c["prompt"] for c in fake_claude.calls(self.bin) if "--safe-mode" not in c["argv"]]
                self.assertTrue(any("VAL-TASK" in p for p in rollouts))  # val is scored, never shown

    def test_train_perfect_at_baseline_calls_no_optimizer(self):
        report = self.go(default={"stream": fake_claude.stream_for(text="Q1")})
        self.assertEqual(report["stop"]["reason"], "train_perfect")
        self.assertEqual(self.llm_prompts(), [])
        self.assertEqual(report["epochs"], [])

    def test_regression_val_perfect_at_baseline_calls_no_optimizer(self):
        # plan 0390 step 7: a real run spent its epochs on candidates that could never beat val at 100%
        report = self.go({"prompt": "VAL-TASK", "stream": fake_claude.stream_for(text="Q1")})
        self.assertEqual(report["baseline"], {"train": 0.0, "val": 1.0})
        self.assertEqual(report["stop"]["reason"], "val_perfect")
        self.assertEqual(self.llm_prompts(), [])
        self.assertEqual(report["tokens"]["rollouts"], 5)

    def test_reflection_error_counts_as_a_rejected_epoch(self):
        claude = fake_claude.install(self.bin, rules=[{"prompt": "## Failed train rollouts", "exit": 1,
                                                       "stream": fake_claude.stream_for(subtype="error_during")}],
                                     default=FAILS)
        job = loop.Run(self.skill, self.tmp / "r2", {"epochs": 3}, workspace=self.tmp / "ws", claude=claude,
                       env=self.env)
        report = job.run()
        self.assertEqual(report["stop"]["reason"], "two_rejected")
        self.assertTrue(all(e["reflection_error"] for e in report["epochs"]))

    def test_unusable_edit_sets(self):
        bad = [{"prompt": "## Failed train rollouts", "stream": fake_claude.stream_for(text=REFLECTION)},
               {"prompt": "## Edit set schema", "stream": fake_claude.stream_for(
                   text=json.dumps([{"op": "delete", "anchor": "NOT IN THE SKILL"}]))}]
        claude = fake_claude.install(self.bin, rules=bad, default=FAILS)
        report = loop.Run(self.skill, self.tmp / "r3", {"epochs": 2, "candidates": 1}, workspace=self.tmp / "ws",
                          claude=claude, env=self.env).run()
        entry = report["epochs"][0]["candidates"][0]
        self.assertEqual((entry["error"], entry["applied"]), ("no edit applied", 0))
        self.assertEqual(report["tokens"]["rollouts"], 5)  # an unchanged candidate is never scored

    def test_skeleton_and_bad_sets_are_refused(self):
        (self.skill / "evals" / "evals.json").write_text(json.dumps(
            __import__("evalset").skeleton("demo")), encoding="utf-8")
        with self.assertRaisesRegex(loop.RunError, "skeleton"):
            loop.Run(self.skill, self.tmp / "r4", {})
        (self.skill / "evals" / "evals.json").write_text(json.dumps(evals(val=0)), encoding="utf-8")
        with self.assertRaisesRegex(loop.RunError, "no val eval"):
            loop.Run(self.skill, self.tmp / "r4", {})
        self.assertFalse((self.tmp / "r4").exists())


if __name__ == "__main__":
    unittest.main()
