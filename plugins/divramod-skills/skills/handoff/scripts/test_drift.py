"""drift.py: `/handoff c`'s step 0 restores the plan's `run` once, then lets the session win; `--clear` passes the
effort; `/handoff` persists `run` with plan.py's `run --sync` (plan 0016 step 5). The session is always faked (a
fixture transcript, a temporary HOME, a cleaned environment), never the real one."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN = HERE.parents[1] / "plan" / "scripts" / "plan.py"
SKILL = HERE.parent / "SKILL.md"
SESSION = "fake-session"
CLEARED = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_EFFORT", "CLAUDE_CONTEXT_WINDOW", "CLAUDE_CODE_DISABLE_1M_CONTEXT",
           "ANTHROPIC_MODEL", "CLAUDE_PID", "HANDOFF_ROOT")
LEGACY = "# Plan 0001: old\n\nRun: opus max\n\n| # | Step | Status |\n|---|---|---|\n| 1 | x | next |\n"


def assistant(model: str, effort: str) -> str:
    return json.dumps({"type": "assistant", "requestedModel": model, "effort": effort,
                       "message": {"usage": {"input_tokens": 10}}})


class DriftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.repo, self.home = base / "repo", base / "home"
        self.repo.mkdir()
        (self.home / ".claude" / "projects" / "p").mkdir(parents=True)
        self.env = {k: v for k, v in os.environ.items() if k not in CLEARED}
        self.env.update({"HOME": str(self.home), "HANDOFF_ROOT": str(base / "data"),
                         "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        self.git("init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("1\n")
        self.commit_all("init")

    def tearDown(self):
        self.tmp.cleanup()

    def run_in(self, *args, env=None) -> subprocess.CompletedProcess:
        return subprocess.run(args, cwd=self.repo, env=env or self.env, text=True, capture_output=True)

    def git(self, *args) -> str:
        out = self.run_in("git", *args)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def commit_all(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def plan(self, *args) -> dict:
        out = self.run_in(sys.executable, str(PLAN), *args)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def record_plan(self, run=("claude-opus-5-5", "max", "1m")) -> Path:
        path = self.repo / self.plan("new", "Tiny")["path"]
        self.plan("run", "--model", run[0], "--effort", run[1], "--window", run[2])
        self.commit_all("plan")
        self.stamp()
        return path

    def stamp(self) -> None:
        """A handoff written at HEAD: where.py --stamp sets its `at`."""
        out = self.run_in(sys.executable, str(HERE / "where.py"), "--stamp")
        self.assertEqual(out.returncode, 0, out.stderr)

    def session(self, model: str, effort: str) -> Path:
        """The faked session: its transcript where session.py finds it by $CLAUDE_CODE_SESSION_ID."""
        path = self.home / ".claude" / "projects" / "p" / f"{SESSION}.jsonl"
        path.write_text(assistant(model, effort) + "\n")
        return path

    def drift(self, *args, **env) -> dict:
        out = self.run_in(sys.executable, str(HERE / "drift.py"), *args, env={**self.env, **env})
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_a_drift_switches_once_then_the_session_wins_for_the_same_handoff(self):
        self.record_plan()
        transcript = self.session("claude-sonnet-5-5", "medium")
        first = self.drift("--transcript", str(transcript))
        self.assertEqual(first["action"], "switch", first)
        self.assertEqual(set(first["drift"]), {"model", "effort"})
        self.assertEqual(first["command"], "hal2-cli-agents switch --model claude-opus-5-5 --effort max "
                                           "--prompt '/handoff c' --detach --json")
        self.assertTrue(Path(first["record"]).is_file())
        second = self.drift("--transcript", str(transcript))
        self.assertEqual(second["action"], "sync", second)
        self.assertTrue(second["command"].endswith("plan.py run --sync"), second["command"])
        (self.repo / "a.txt").write_text("2\n")
        self.commit_all("more work")
        self.stamp()
        self.assertEqual(self.drift("--transcript", str(transcript))["action"], "switch")

    def test_an_effort_drift_alone_switches(self):
        self.record_plan()
        out = self.drift("--transcript", str(self.session("claude-opus-5-5[1m]", "medium")))
        self.assertEqual((out["action"], list(out["drift"])), ("switch", ["effort"]), out)

    def test_the_session_found_by_its_id_is_read(self):
        self.record_plan()
        self.session("claude-sonnet-5-5", "high")
        self.assertEqual(self.drift(CLAUDE_CODE_SESSION_ID=SESSION)["action"], "switch")

    def test_a_match_or_a_window_only_drift_is_ok(self):
        self.record_plan()
        transcript = str(self.session("claude-opus-5-5", "max"))
        self.assertEqual(self.drift("--transcript", transcript)["action"], "ok")
        out = self.drift("--transcript", transcript, CLAUDE_CONTEXT_WINDOW="200000")
        self.assertEqual((out["action"], list(out["drift"])), ("ok", ["window"]), out)

    def test_a_legacy_run_line_or_no_plan_is_ok(self):
        transcript = str(self.session("claude-sonnet-5-5", "low"))
        self.assertEqual(self.drift("--transcript", transcript)["why"], "no plan")
        plan = self.repo / "plans" / "0001-old" / "plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(LEGACY)
        (self.repo / "plans" / "CURRENT_PLAN").write_text("0001-old\n")
        out = self.drift("--transcript", transcript)
        self.assertEqual((out["action"], out["run"]), ("ok", None), out)

    def test_clear_passes_the_effort_of_run_and_none_without_a_plan(self):
        self.assertEqual(self.drift("--clear")["command"], "hal2-cli-agents clear-and-continue --detach --json")
        self.record_plan(("claude-opus-5-5", "xhigh", "1m"))
        self.assertEqual(self.drift("--clear")["command"],
                         "hal2-cli-agents clear-and-continue --effort xhigh --detach --json")

    def test_run_sync_and_commit_handoff_commit_the_new_run(self):
        path = self.record_plan()
        self.session("claude-sonnet-5-5", "high")
        out = self.run_in(sys.executable, str(PLAN), "run", "--sync",
                          env={**self.env, "CLAUDE_CODE_SESSION_ID": SESSION})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["run"], "claude-sonnet-5-5 high 1m")
        rel = str(path.relative_to(self.repo))
        out = self.run_in("bash", str(HERE / "commit-handoff.sh"), "docs: handoff", rel)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("run: claude-sonnet-5-5 high 1m", self.git("show", f"HEAD:{rel}"))
        committed = self.git("show", "--name-only", "--format=", "HEAD").split()
        self.assertEqual([f for f in committed if f != ".gitignore"], [rel])  # .gitignore: the root HANDOFF.md line


class SkillOrderTest(unittest.TestCase):
    def test_continue_restores_before_it_reads_and_never_syncs_first(self):
        text = SKILL.read_text()
        cont = text[text.index("\n## Continue\n"):text.index("\n## Write\n")]
        self.assertLess(cont.index("\n0. **Restore"), cont.index("\n1. Read the handoff"))
        blocks = re.findall(r"```bash\n(.*?)```", cont, re.S)
        self.assertIn("drift.py", blocks[0])
        self.assertFalse([b for b in blocks if "--sync" in b], "Continue runs no --sync of its own")

    def test_write_persists_run_before_the_handoff_is_stamped_and_clear_takes_the_effort(self):
        text = SKILL.read_text()
        self.assertLess(text.index("### 3b. Persist the coordinator's values"), text.index("where.py --stamp` writes"))
        self.assertIn("plan.py run --sync", text[text.index("### 3b."):text.index("### 4.")])
        clear = text[text.index("\n## Clear and continue\n"):]
        self.assertIn("drift.py --clear", clear)


if __name__ == "__main__":
    unittest.main()
