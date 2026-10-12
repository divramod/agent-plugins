import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import loop  # noqa: E402
import tick  # noqa: E402
from test_scan import lines, run, scratch_repo  # noqa: E402

FAKE = """#!/bin/sh
# Answers from $FAKE_DIR: agents.json, queue.json, spawn.json; every call is logged to calls.log.
echo "$(basename "$0") $*" >> "$FAKE_DIR/calls.log"
case "$1 $2" in
  "list --json") cat "$FAKE_DIR/agents.json" ;;
  "worktree queue") cat "$FAKE_DIR/queue.json" ;;
esac
"""
FAKE_CREATE = """import os, sys
# create-worktree-session's create.py: logs its call, answers spawn.json.
with open(os.path.join(os.environ["FAKE_DIR"], "calls.log"), "a") as log:
    log.write("create.py " + " ".join(sys.argv[1:]) + "\\n")
print(open(os.path.join(os.environ["FAKE_DIR"], "spawn.json")).read())
"""
COORDINATOR = ("You are the plan's coordinator: you never do a step yourself; each step runs in one subagent at its "
               "row's Model and Effort, sized under 35% of its Window; you check its done-when, commit it and keep "
               "`run` current.")
BIG = "code/typescript/apps/big"


@unittest.skipIf(shutil.which("scc") is None, "scc is not installed")
class Loop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = scratch_repo(base).resolve()
        self.fake = base / "fake"
        self.fake.mkdir()
        for name in ("hal2-cli-agents", "hal2-cli-git"):
            path = self.fake / name
            path.write_text(FAKE)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        (self.fake / "create.py").write_text(FAKE_CREATE)
        self.create = loop.CREATE
        loop.CREATE = self.fake / "create.py"
        self.env = {k: os.environ.get(k) for k in ("PATH", "FAKE_DIR", "FIX_LOC_ROOT")}
        os.environ.update(PATH=f"{self.fake}:{os.environ['PATH']}", FAKE_DIR=str(self.fake),
                          FIX_LOC_ROOT=str(base / "state"))
        self.worktree = base / "wt01"
        self.answer(agents=[], queue={"queue": []},
                    spawn={"project": str(self.repo), "slot": "01", "pane": "t:abc", "worktree": str(self.worktree)})

    def tearDown(self):
        loop.CREATE = self.create
        for key, value in self.env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def answer(self, **answers):
        for name, value in answers.items():
            (self.fake / f"{name}.json").write_text(json.dumps(value))

    def calls(self):
        log = self.fake / "calls.log"
        return log.read_text().splitlines() if log.exists() else []

    def spawn(self, now):
        result = loop.run_tick(self.repo, now=now)
        self.assertEqual((result["action"], result["unit"]), ("next", BIG))
        return result

    def land(self, plan, text):
        """Commit `plan`'s Finished plan.md and `text` as big's a.ts on origin's main."""
        Path(self.repo, BIG, "src/a.ts").write_text(text)
        Path(self.repo, "plans", plan).mkdir(parents=True)
        Path(self.repo, "plans", plan, "plan.md").write_text("# Plan\n\nFinished: 2026-09-30\n")
        run(self.repo, "git", "add", "-A")
        run(self.repo, "git", "commit", "-q", "-m", "land")
        run(self.repo, "git", "push", "-q", "origin", "main")

    def test_dry_run_names_the_hotspot_and_its_command_without_spawning(self):
        result = loop.run_tick(self.repo, dry_run=True)
        self.assertEqual(result["action"], "next")
        self.assertEqual(result["files"], [f"{BIG}/src/a.ts"])
        self.assertEqual(result["command"][1:], [str(self.fake / "create.py"), "--repo", str(self.repo), "--from", "30",
                                                 "--model", "claude-sonnet-5-5", "--effort", "medium", "--exact",
                                                 "--prompt", "<prompt>"])
        self.assertIn(f"`{BIG}/src/a.ts` (40)", result["prompt"])
        self.assertIn(COORDINATOR, result["prompt"])
        self.assertIn("by default sonnet medium 1m", result["prompt"])
        self.assertIn("at most 10 code lines", result["prompt"])
        self.assertNotIn("{", result["prompt"])
        self.assertFalse(loop.state_path(self.repo).exists())
        self.assertFalse([c for c in self.calls() if " spawn " in c])

    def test_next_spawns_and_records_the_servant(self):
        self.spawn(1_000)
        servant = loop.load(self.repo)["servant"]
        self.assertEqual((servant["slot"], servant["pane"], servant["before"]), ("01", "t:abc", {f"{BIG}/src/a.ts": 40}))
        self.assertEqual((servant["model"], servant["effort"], servant["step_model"]),
                         ("claude-sonnet-5-5", "medium", "sonnet"))
        self.assertTrue(any(c.startswith("create.py --repo") and "--from 30" in c for c in self.calls()))

    def test_coordinator_and_step_values_are_kept_in_the_state(self):
        result = loop.run_tick(self.repo, model="claude-opus-5-5", effort="high", step_model="opus", dry_run=True)
        self.assertIn("--effort", result["command"])
        self.assertEqual(result["command"][result["command"].index("--model") + 1], "claude-opus-5-5")
        self.assertIn("by default opus medium 1m", result["prompt"])
        loop.run_tick(self.repo, model="claude-opus-5-5", effort="high", step_model="opus", now=1_000)
        self.assertEqual(loop.load(self.repo)["settings"], {"coordinator_model": "claude-opus-5-5",
                                                            "coordinator_effort": "high", "step_model": "opus"})
        state = loop.load(self.repo)
        state["servant"] = None
        loop.save(self.repo, state)
        later = loop.run_tick(self.repo, dry_run=True)  # no flags: the stored values
        self.assertEqual(later["command"][later["command"].index("--effort") + 1], "high")
        self.assertEqual(loop.status(self.repo)["settings"]["step_model"], "opus")

    def test_wait_while_the_servant_works(self):
        self.spawn(1_000)
        self.answer(agents=[{"project": str(self.repo), "slot": "01", "state": "working", "since": 1_000}])
        self.assertEqual(loop.run_tick(self.repo, now=1_000 + 10 * tick.MINUTE)["reason"], "the servant is working")

    def test_claim_names_the_plan(self):
        self.spawn(1_000)
        run(self.repo, "git", "worktree", "add", "-q", "-b", "01", str(self.worktree))
        self.assertEqual(loop.claim(self.worktree, "0090-fix-loc-big")["plan"], "0090-fix-loc-big")
        self.assertEqual(loop.load(self.repo)["servant"]["plan"], "0090-fix-loc-big")

    def test_paused_notifies_once(self):
        self.spawn(1_000)
        self.answer(agents=[{"project": str(self.repo), "slot": "01", "state": "done", "since": 1_000}],
                    queue={"queue": [{"slot": "01", "worktree": str(self.worktree), "state": "held", "hold": {"reason": "failed"}}]})
        first = loop.run_tick(self.repo, now=2_000)
        self.assertEqual((first["action"], len(first["notify"])), ("paused", 1))
        self.assertEqual(loop.run_tick(self.repo, now=3_000)["notify"], [])

    def test_blocked_skips_the_unit_and_starts_the_next(self):
        self.spawn(1_000)
        result = loop.run_tick(self.repo, now=1_000 + 10 * tick.MINUTE)
        self.assertEqual((result["action"], result["unit"]), ("next", "code/typescript/apps/small"))
        self.assertIn(BIG, loop.load(self.repo)["blocked"])
        self.assertTrue(result["notify"])

    def test_landed_records_the_counts_kills_the_host_and_moves_on(self):
        self.spawn(1_000)
        state = loop.load(self.repo)
        state["servant"]["plan"] = "0090-fix-loc-big"
        loop.save(self.repo, state)
        self.land("0090-fix-loc-big", lines(8))
        result = loop.run_tick(self.repo, now=2_000)
        self.assertEqual((result["action"], result["unit"]), ("next", "code/typescript/apps/small"))
        entry = loop.load(self.repo)["history"][0]
        self.assertEqual((entry["before"], entry["after"], entry["still_over"]),
                         ({f"{BIG}/src/a.ts": 40}, {f"{BIG}/src/a.ts": 8}, []))
        self.assertIn("hal2-cli-agents terminal kill abc", self.calls())

    def test_record_and_status(self):
        loop.record(self.repo, started=True, stopped=False)
        self.assertIsNotNone(loop.status(self.repo)["started_ms"])


class Cli(unittest.TestCase):
    def test_tick_needs_its_tools(self):
        env = {**os.environ, "PATH": "/usr/bin:/bin"}
        out = subprocess.run([sys.executable, str(Path(loop.__file__)), "tick"], env=env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)
        self.assertIn("install-prerequisites", out.stderr)


if __name__ == "__main__":
    unittest.main()
