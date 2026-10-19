"""Tests of rollout.py with the fake `claude` (never the real one, 0 tokens)."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fake_claude
import rollout

EVAL = {"id": "open-1", "prompt": "Show me the open questions.", "files": ["evals/files/QUESTIONS.md"]}
CANDIDATE = "---\nname: demo\ndescription: d\n---\n\n# demo\n\nRun `python3 $S/q.py`.\n"


def tree(folder):
    """{relative path: sha256} of every file under folder."""
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(folder).rglob("*")) if p.is_file()}


class RolloutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.claude = fake_claude.install(self.bin)
        self.skill = self.tmp / "skills" / "demo"
        (self.skill / "scripts").mkdir(parents=True)
        (self.skill / "SKILL.md").write_text("old text\n", encoding="utf-8")
        (self.skill / "scripts" / "q.py").write_text("print('q')\n", encoding="utf-8")
        (self.skill / "evals" / "files").mkdir(parents=True)
        (self.skill / "evals" / "evals.json").write_text('{"secret": "val tasks"}', encoding="utf-8")
        (self.skill / "evals" / "files" / "QUESTIONS.md").write_text("## Q1\n", encoding="utf-8")
        self.ws = self.tmp / "ws"
        self.env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.tmp), "ANTHROPIC_API_KEY": "k",
                    "ANTHROPIC_AUTH_TOKEN": "t", "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli",
                    "CLAUDE_CODE_OAUTH_TOKEN": "o", "OPTIMIZE_KEEP": "1"}

    def run_one(self, eval_case=EVAL, **kw):
        kw.setdefault("claude", self.claude)
        return rollout.run("demo", CANDIDATE, eval_case, skill_dir=self.skill, workspace=self.ws, env=self.env, **kw)

    def test_result_shape(self):
        result = self.run_one()
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(result["eval_id"], "open-1")
        self.assertEqual(result["skills"], ["demo"])
        self.assertEqual(result["final_text"], "done")
        self.assertEqual(result["usage"]["total"], 84966)
        self.assertFalse(result["truncated"])
        for key in ("tool_calls", "transcript", "cost_usd", "num_turns", "subtype", "error", "duration_s"):
            self.assertIn(key, result)

    def test_command_flags(self):
        self.run_one(model="sonnet", max_turns=5, budget_usd="0.20")
        (call,) = fake_claude.calls(self.bin)
        argv = call["argv"]
        self.assertEqual(argv[:2], ["-p", "Show me the open questions."])
        flag = {argv[i]: argv[i + 1] for i in range(2, len(argv) - 1) if argv[i].startswith("--")}
        self.assertEqual(flag["--output-format"], "stream-json")
        self.assertEqual(flag["--model"], "sonnet")
        self.assertEqual(flag["--setting-sources"], "project")
        self.assertEqual(flag["--max-turns"], "5")
        self.assertEqual(flag["--max-budget-usd"], "0.20")
        self.assertEqual(flag["--tools"], "Skill,Bash,Read,Glob,Grep")
        self.assertEqual(flag["--allowedTools"], "Skill,Read,Glob,Grep")  # Bash only sandboxed (review 3)
        self.assertEqual(flag["--permission-prompts"], "none")
        sandbox = json.loads(flag["--settings"])["sandbox"]
        self.assertEqual((sandbox["enabled"], sandbox["failIfUnavailable"], sandbox["allowUnsandboxedCommands"],
                          sandbox["autoAllowBashIfSandboxed"]), (True, True, False, True))
        self.assertEqual(sandbox["network"], {"strictAllowlist": True, "allowedDomains": []})
        self.assertNotIn("excludedCommands", sandbox)
        self.assertNotIn("filesystem", sandbox)  # no write grant beyond the workspace and the sandbox's temp
        for needed in ("--verbose", "--no-session-persistence", "--strict-mcp-config"):
            self.assertIn(needed, argv)
        self.assertNotIn("--disable-slash-commands", argv)  # it would disable the candidate skill

    def test_no_api_key_in_child_env(self):
        self.run_one()
        (call,) = fake_claude.calls(self.bin)
        for gone in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
            self.assertNotIn(gone, call["env"])
        self.assertEqual(call["env"]["CLAUDE_CODE_OAUTH_TOKEN"], "o")
        self.assertEqual(call["env"]["OPTIMIZE_KEEP"], "1")

    def test_no_api_key_from_process_env(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k2"}):
            rollout.run("demo", CANDIDATE, EVAL, skill_dir=self.skill, workspace=self.ws, claude=self.claude)
        (call,) = fake_claude.calls(self.bin)
        self.assertNotIn("ANTHROPIC_API_KEY", call["env"])

    def test_workspace_holds_candidate_without_evals(self):
        self.run_one()
        (call,) = fake_claude.calls(self.bin)
        self.assertEqual(Path(call["cwd"]).resolve(), self.ws.resolve())
        self.assertEqual(call["skills"], {"demo": CANDIDATE})
        skill = self.ws / ".claude" / "skills" / "demo"
        self.assertTrue((skill / "scripts" / "q.py").is_file())
        self.assertFalse((skill / "evals").exists())
        self.assertEqual((self.ws / "QUESTIONS.md").read_text(encoding="utf-8"), "## Q1\n")

    def test_skill_folder_never_written(self):
        before = tree(self.skill)
        self.run_one()
        self.run_one()
        self.assertEqual(tree(self.skill), before)

    def test_workspace_rebuilt_each_rollout(self):
        self.run_one()
        (self.ws / "stale.txt").write_text("left over", encoding="utf-8")
        self.run_one({"id": "2", "prompt": "p", "files": [{"dest": "in/x.md", "text": "inline"}]})
        self.assertFalse((self.ws / "stale.txt").exists())
        self.assertFalse((self.ws / "QUESTIONS.md").exists())
        self.assertEqual((self.ws / "in" / "x.md").read_text(encoding="utf-8"), "inline")

    def test_support_files(self):
        shared = self.tmp / "plugin-scripts"
        shared.mkdir()
        (shared / "skillpath.py").write_text("x = 1\n", encoding="utf-8")
        self.run_one(support={".claude/scripts": shared, ".claude/.claude-plugin": None})
        self.assertTrue((self.ws / ".claude" / "scripts" / "skillpath.py").is_file())
        self.assertTrue((self.ws / ".claude" / ".claude-plugin").is_dir())

    def test_refuses_foreign_folder_and_escapes(self):
        foreign = self.tmp / "mine"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("precious", encoding="utf-8")
        result = rollout.run("demo", CANDIDATE, EVAL, skill_dir=self.skill, workspace=foreign, claude=self.claude,
                             env=self.env)
        self.assertFalse(result["ok"])
        self.assertIn("not an optimize-skill workspace", result["error"])
        self.assertTrue((foreign / "keep.txt").is_file())
        escape = self.run_one({"id": "3", "prompt": "p", "files": [{"dest": "../out.md", "text": "x"}]})
        self.assertIn("leaves the workspace", escape["error"])
        self.assertFalse((self.tmp / "out.md").exists())
        self.assertEqual(fake_claude.calls(self.bin), [])
        bad = rollout.run("../x", CANDIDATE, EVAL, workspace=self.ws, claude=self.claude, env=self.env)
        self.assertIn("bad skill name", bad["error"])

    def test_error_stream_and_exit(self):
        fake_claude.set_rules(self.bin, [{"prompt": "budget", "exit": 1,
                                          "stream": fake_claude.stream_for("x", subtype="error_max_budget_usd")}])
        result = self.run_one({"id": "b", "prompt": "budget please"})
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"].startswith("error_max_budget_usd"))
        self.assertGreater(result["usage"]["total"], 0)  # charged in full even on a stop

    def test_no_result_event(self):
        fake_claude.set_rules(self.bin, [{"stream": "garbage\n", "exit": 3}])
        result = self.run_one()
        self.assertFalse(result["ok"])
        self.assertIn("no result event (exit 3)", result["error"])
        self.assertTrue(result["truncated"])  # review 2: the loop charges it at least its estimate

    def test_timeout(self):
        fake_claude.set_rules(self.bin, [{"sleep": 5, "stream": fake_claude.stream_for()}])
        result = self.run_one(timeout=0.5)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "timeout")
        self.assertTrue(result["truncated"])
        self.assertLess(result["duration_s"], 4)

    def test_missing_binary_and_env_binary(self):
        result = self.run_one(claude=str(self.tmp / "nope"))
        self.assertTrue(result["error"].startswith("start:"))
        self.assertFalse(result["truncated"])  # never started: nothing to charge
        with mock.patch.dict(os.environ, {"OPTIMIZE_SKILL_CLAUDE": self.claude}):
            self.assertTrue(self.run_one(claude=None)["ok"])

    def test_rule_by_skill_text(self):
        fake_claude.set_rules(self.bin, [{"skill": "q.py", "stream": fake_claude.stream_for("matched")}])
        self.assertEqual(self.run_one()["final_text"], "matched")


if __name__ == "__main__":
    unittest.main()
