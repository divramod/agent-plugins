"""`plan.py end` (plan_end.py; hal2 plan 0514 step 2, D5, D6): the plan's end as one call. A scratch field
`hal2/41` with a bare origin, fake `hal2-cli-git` and `hal2-cli-workqueue` on PATH, a fake tollman.sh, a pre-push
hook that records the run state it sees (the push runs as `pushing`) or fails. Replays fields 09/23/29: every step
done, the push behind a workqueue hold, then the hitch without a nudge."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import plan_end
import runstate
import testkit

SCRIPT = Path(__file__).resolve().parent / "plan.py"
SLUG = "0007-end-test"
PLAN = """---
type: Plan
schema: 1
id: 7
title: "end test"
description: "x"
status: open
landing: {landing}
created: 2026-10-31
---

# Plan 0007: end test

## Steps

| # | Step | Done when | Status |
|---|---|---|---|
| 1 | one | a check | done |
| 2 | two | a check | {last} |
"""
GIT_FAKE = """#!/bin/sh
# hal2-cli-git: `worktree queue mode ... --json` prints the mode file, `worktree queue ready` logs and answers
base='{base}'
case "$*" in
  *"queue mode"*) printf '{{"mode": "%s"}}\\n' "$(cat "$base/mode")" ;;
  *"queue ready"*)
    printf '%s\\n' "$*" >> "$base/ready.log"
    if [ -f "$base/ready-fails" ]; then echo "refused: nothing the default branch lacks" >&2; exit 1; fi
    echo '{{"status": "ready"}}' ;;
  *) exit 2 ;;
esac
"""


class PlanEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "hal2" / "41"
        self.origin = self.base / "origin.git"
        if PlanEndTest.template is None:  # the field and its origin made once, every test gets a copy (fast-tests)
            PlanEndTest.template = Path(testkit._scratch()) / "end"
            self.build(PlanEndTest.template)
        shutil.copytree(PlanEndTest.template, self.base, dirs_exist_ok=True, symlinks=True)
        (self.root / "plans" / "CURRENT_PLAN").write_text(SLUG + "\n")
        bin_dir = self.base / "bin"
        bin_dir.mkdir()
        self.fake(bin_dir / "hal2-cli-git", GIT_FAKE.format(base=self.base))
        self.fake(bin_dir / "hal2-cli-workqueue", f"#!/bin/sh\ncat '{self.base}/workqueue.json'\n")
        (self.base / "workqueue.json").write_text(json.dumps(
            {"schema": 1, "waiting": [], "holds": [{"field": "jobsearch/05", "class": "landing"}]}))
        (self.base / "mode").write_text("production")
        self.tollman = self.base / "tollman.sh"
        self.awake(True)
        self.hook("cp plans/PLAN_STATE '{base}/seen'\nexit 0\n")
        missing = str(self.base / "no-such-binary")  # never the real plan store's CLI
        self.env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HAL2_CLI_PLANS": missing,
                    "HAL2_CLI_RECORDS": missing,
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                    "GIT_COMMITTER_EMAIL": "t@t"}

    def tearDown(self):
        self.tmp.cleanup()

    # fixtures

    template: Path | None = None

    def build(self, base: Path) -> None:
        """Field `hal2/41` on branch 41 with the plan committed; origin a bare repository beside it, named by a path
        relative to the field (every git call runs in the field), so a copy of `base` pushes to its own origin."""
        root = base / "hal2" / "41"
        subprocess.run(["git", "init", "-q", "--bare", str(base / "origin.git")], check=True)
        testkit.init_repo(root, branch="41")
        (root / ".gitignore").write_text("plans/CURRENT_PLAN\nplans/PLAN_STATE\n")
        (root / "README.md").write_text("field 41\n")
        saved, self.root = self.root, root
        try:
            self.plan_file(landing="auto", last="done")
            self.git("remote", "add", "origin", "../../origin.git")
            self.git("add", "-A")
            self.git("commit", "-qm", "the plan")
        finally:
            self.root = saved

    def git(self, *args) -> str:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True,
                              env=env).stdout.strip()

    def plan_file(self, landing: str, last: str) -> None:
        path = self.root / "plans" / SLUG / "plan.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PLAN.format(landing=landing, last=last))

    @staticmethod
    def fake(path: Path, text: str) -> None:
        path.write_text(text)
        path.chmod(0o755)

    def awake(self, yes: bool) -> None:
        self.fake(self.tollman, "#!/bin/sh\necho yes\n" if yes else
                  "#!/bin/sh\necho 'tollman.sh: the tollman sleeps' >&2\necho no\n")

    def hook(self, body: str) -> None:
        self.fake(self.root / ".git" / "hooks" / "pre-push", "#!/bin/sh\n" + body.format(base=self.base))

    def end(self, *args) -> tuple[int, dict]:
        with mock.patch.object(plan_end, "tollman_script", return_value=self.tollman):
            done = testkit.run(SCRIPT, ["end", "--json", *args], env=self.env, cwd=self.root)
        return done.returncode, json.loads(done.stdout)

    def state(self) -> dict | None:
        return runstate.read(self.root, SLUG)

    def remote_head(self) -> str:
        return subprocess.run(["git", "-C", str(self.origin), "rev-parse", "--verify", "-q", "refs/heads/41"],
                              capture_output=True, text=True).stdout.strip()

    def ready_calls(self) -> list[str]:
        log = self.base / "ready.log"
        return log.read_text().splitlines() if log.exists() else []

    # refusals

    def test_an_open_step_is_refused_and_nothing_is_pushed(self):
        self.plan_file(landing="auto", last="next")
        self.git("commit", "-qam", "reopen")
        code, out = self.end()
        self.assertEqual((code, out["action"], out["schema"]), (1, "refused", 1))
        self.assertIn("step 2 is still open", out["why"])
        self.assertEqual((self.remote_head(), self.state(), self.ready_calls()), ("", None, []))

    def test_a_manual_plan_is_refused(self):
        self.plan_file(landing="manual", last="done")
        self.git("commit", "-qam", "manual")
        code, out = self.end()
        self.assertEqual((code, out["action"]), (1, "refused"))
        self.assertIn("/mtm", out["why"])

    def test_a_dirty_tree_is_refused_naming_the_files_and_nothing_is_committed(self):
        (self.root / "README.md").write_text("changed\n")
        (self.root / "loose.txt").write_text("x")
        head = self.git("rev-parse", "HEAD")
        code, out = self.end()
        self.assertEqual((code, out["action"]), (1, "refused"))
        self.assertIn("README.md", out["why"])
        self.assertNotIn("loose.txt", out["why"])  # untracked is no refusal
        self.assertEqual((self.git("rev-parse", "HEAD"), self.remote_head(), self.state()), (head, "", None))

    def test_the_default_branch_is_refused(self):
        self.git("checkout", "-qb", "main")
        code, out = self.end()
        self.assertEqual((code, out["action"]), (1, "refused"))
        self.assertIn("default branch", out["why"])

    def test_a_servant_field_is_refused(self):
        (self.root / "plans" / "LEAD").write_text(f"07 {SLUG} 2\n")
        with mock.patch.object(plan_end, "tollman_script", return_value=self.tollman):
            done = testkit.run(SCRIPT, ["end"], env=self.env, cwd=self.root)
        self.assertEqual(done.returncode, 1)
        self.assertIn("servant", done.stderr)
        self.assertEqual(self.remote_head(), "")

    # the end

    def test_push_then_hitch_writes_pushing_then_hitched(self):
        code, out = self.end()
        self.assertEqual((code, out["action"], out["state"], out["pushed"]), (0, "hitched", "hitched", "pushed"))
        self.assertEqual(self.remote_head(), self.git("rev-parse", "HEAD"))
        seen = json.loads((self.base / "seen").read_text())  # what the pre-push hook saw: the push is a state
        self.assertEqual((seen["state"], seen["plan"]), ("pushing", SLUG))
        self.assertIn("jobsearch/05 (landing)", seen["why"])
        self.assertEqual(self.state()["state"], "hitched")
        self.assertEqual(self.ready_calls(), ["worktree queue ready --json"])

    def test_a_pushed_head_is_not_pushed_again_and_still_hitches(self):
        self.git("push", "-q", "--no-verify", "origin", "41")
        code, out = self.end()
        self.assertEqual((code, out["action"], out["pushed"]), (0, "hitched", "up-to-date"))
        self.assertFalse((self.base / "seen").exists())

    def test_tollman_asleep_is_done_and_names_mtm(self):
        self.awake(False)
        code, out = self.end()
        self.assertEqual((code, out["action"], out["state"], out["next"]), (0, "mtm", "done", "/mtm"))
        self.assertIn("sleeps", out["why"])
        self.assertEqual(self.remote_head(), self.git("rev-parse", "HEAD"))  # pushed all the same
        self.assertEqual(self.ready_calls(), [])
        self.assertEqual(self.state()["state"], "done")

    def test_smuggle_mode_names_mtm_and_never_hitches(self):
        (self.base / "mode").write_text("smuggle")
        code, out = self.end()
        self.assertEqual((code, out["action"], out["next"]), (0, "smuggle", "/mtm"))
        self.assertEqual(self.ready_calls(), [])

    def test_a_failed_push_is_blocked_with_the_hooks_words(self):
        self.hook("echo 'lint: plans/uats.md is stale' >&2\nexit 1\n")
        code, out = self.end()
        self.assertEqual((code, out["action"], out["state"]), (1, "blocked", "blocked"))
        self.assertIn("plans/uats.md is stale", out["why"])
        state = self.state()
        self.assertEqual(state["state"], "blocked")
        self.assertIn("git push failed", state["why"])
        self.assertEqual((self.remote_head(), self.ready_calls()), ("", []))

    def test_a_refused_hitch_is_blocked(self):
        (self.base / "ready-fails").write_text("")
        code, out = self.end()
        self.assertEqual((code, out["action"]), (1, "blocked"))
        self.assertIn("nothing the default branch lacks", self.state()["why"])

    def test_dry_run_changes_nothing(self):
        code, out = self.end("--dry-run")
        self.assertEqual((code, out["action"]), (0, "dry-run"))
        self.assertIn("would push 41, then hitch", out["why"])
        self.assertEqual((self.remote_head(), self.state(), self.ready_calls()), ("", None, []))

    # the parts

    def test_the_push_why_names_this_fields_wait_first(self):
        queue = {"waiting": [{"field": "hal2/41", "position": 3}], "holds": [{"field": "jobsearch/05"}]}
        self.assertEqual(plan_end.push_why(self.root, queue), "pre-push hook waits in the workqueue (place 3)")
        self.assertEqual(plan_end.push_why(self.root, {}), "pre-push hook")
        self.assertEqual(plan_end.push_why(self.root, {"holds": [{"field": "hal2/41"}]}), "pre-push hook")

    def test_mtms_tollman_script_is_found_beside_the_plan_skill(self):
        found = plan_end.tollman_script()
        if found is None:
            self.skipTest("the merge-to-main skill is not installed beside the plan skill")
        self.assertEqual((found.name, found.parent.parent.name), ("tollman.sh", "merge-to-main"))


if __name__ == "__main__":
    unittest.main()
