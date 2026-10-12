#!/usr/bin/env python3
"""Tests for check-agent-starts.py, and the check over this repository (hal2 plan 0212)."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("check_agent_starts", HERE / "check-agent-starts.py")
check_agent_starts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_agent_starts)

PLANTED = 'subprocess.run("claude --dangerously-skip-permissions", shell=True)\n'


def repo(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return root


class TestCheckAgentStarts(unittest.TestCase):
    def test_this_repository_starts_no_agent_itself(self):
        self.assertEqual(check_agent_starts.check(HERE.parent), [])

    def test_a_planted_start_and_a_typed_exit_fail(self):
        found = check_agent_starts.check(repo({
            "skills/a/scripts/a.py": PLANTED,
            "skills/b/scripts/b.py": 'subprocess.run(["codex", "exec", "go"])\n',
            "skills/c/scripts/c.sh": 'claude -p "hi"\n',
            "skills/d/scripts/d.py": 'send(pane, "/exit")\n',
        }))
        self.assertEqual(sorted(p.split(":")[0] for p in found),
                         ["skills/a/scripts/a.py", "skills/b/scripts/b.py", "skills/c/scripts/c.sh",
                          "skills/d/scripts/d.py"])

    def test_worktree_run_names_comments_docs_and_tests_pass(self):
        self.assertEqual(check_agent_starts.check(repo({
            "skills/a/scripts/a.py": 'argv = ["hal2-cli-git", "worktree", "run", "03", "--agent", "claude", "--detach"]\n'
                                     'AGENTS = ("claude", "codex", "opencode")\n'
                                     '# claude --resume is what a person types\n',
            "skills/a/SKILL.md": PLANTED,
            "skills/a/scripts/test_a.py": PLANTED,
        })), [])


if __name__ == "__main__":
    unittest.main()
