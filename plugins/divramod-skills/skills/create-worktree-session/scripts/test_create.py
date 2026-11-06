#!/usr/bin/env python3
"""Tests for create.py with fake hal2 CLIs and a fake login shell on PATH (offline: no agent is started)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("HAL2_OVERLAP", "off")  # the start paths' overlap scan (~25 s) has its own tests
TEXT = {"lines": ["CLI-LINE-1"], "context": "- CLI-CONTEXT", "report": "CLI-REPORT"}  # markers no Python format makes

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:] + ["TMUX=" + os.environ.get("TMUX", "")]) + "\n")
args, repo = sys.argv[1:], os.environ["FAKE_REPO"]
name = os.path.basename(repo)
if args[:1] == ["list"]:
    print(json.dumps([{"pane_id": "%1", "slot": "01", "state": "idle", "project": repo},
                      {"pane_id": "%2", "slot": "05", "state": "ended", "project": repo}]))
elif args[:2] == ["terminal", "list"]:
    print(json.dumps([{"worktree": "/wt/" + name + "/02", "alive": True},
                      {"worktree": "/wt/" + name + "/03", "alive": False}]))
elif args[:2] == ["worktree", "list"]:
    w = lambda n, **k: {"name": n, "path": "/wt/" + n, **k}
    extra = [{"name": n, "path": os.path.join(os.environ["FAKE_WT"], n)}
             for n in os.environ.get("FAKE_EXTRA", "").split(",") if n]
    print(json.dumps({"worktrees": [{"name": "main", "main": True}, w("01"), w("02"),
        w("03", plan="0085-old"), w("04", main_ahead=3), w("05", dirty=True), w("06", main_behind=400),
        w("07")] + extra}))
elif args[:2] == ["worktree", "paused"]:
    if os.environ.get("FAKE_PAUSED"):
        print(json.dumps({"schema": 1, "repo": name, "fields": [
            {"field": f, "by": "farmer", "why": "benchmark", "since": "2026-10-28T10:00:00Z"}
            for f in os.environ["FAKE_PAUSED"].split(",")]}))
    else:
        sys.exit(2)  # an older CLI without the command
elif args[:2] == ["worktree", "queue"]:
    print(json.dumps({"queue": [{"repo": name, "slot": "07", "state": "held"}]}))
elif args[:2] == ["worktree", "run"]:
    print("setup ...")
    print(json.dumps({"mode": "terminal", "pane": "t:abc", "slot": args[2], "worktree": os.path.join(os.environ["FAKE_WT"], args[2])}))
'''

PLANS = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(["hal2-cli-plans"] + sys.argv[1:]) + "\n")
if os.environ.get("FAKE_PLANS_FAIL"):
    sys.stderr.write("plan 0376 has no step 9\n")
    sys.exit(2)
print("{}")
'''

SHELL = '#!/bin/sh\n# a login shell without the login: runs the command it gets with -lc\nexec /bin/sh -c "$2"\n'

# hal2: create.py's free-disk check reads shutil.disk_usage; a sitecustomize on PYTHONPATH makes the subprocesses see
# FAKE_FREE_GB (default 1000) free, so the tests pass on a machine or CI runner with less than 50 GB free.
DISK = """import collections, os, shutil
_usage = collections.namedtuple("usage", "total used free")
_free = int(float(os.environ.get("FAKE_FREE_GB", "1000")) * 2**30)
shutil.disk_usage = lambda path: _usage(_free, 0, _free)
"""


class TestCreate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.repo = t / "app"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.bin = t / "bin"
        self.bin.mkdir()
        for name in ("hal2-cli-agents", "hal2-cli-git"):
            (self.bin / name).write_text(FAKE)
            (self.bin / name).chmod(0o755)
        (self.bin / "hal2-cli-plans").write_text(PLANS)
        (self.bin / "hal2-cli-plans").chmod(0o755)
        (self.bin / "fakeshell").write_text(SHELL)
        (self.bin / "fakeshell").chmod(0o755)
        (self.bin / "sitecustomize.py").write_text(DISK)
        self.log = t / "log"
        self.home = t / "home"
        self.wt = self.home / ".hal" / "git" / "worktree" / "app"  # hal2's worktree base of the repo app
        (self.wt / "07").mkdir(parents=True)  # the foreman's field

    def tearDown(self):
        self.tmp.cleanup()

    def run_create(self, *args, extra="") -> dict:
        r = self.run_raw(*args, extra=extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def refused(self, *args, extra="") -> str:
        r = self.run_raw(*args, extra=extra)
        self.assertEqual(r.returncode, 1, r.stdout)
        return r.stderr

    def run_raw(self, *args, extra="", paused="", plans_fail="", overlap="off") -> subprocess.CompletedProcess:
        env = dict(os.environ, HAL2_OVERLAP=overlap, FAKE_PLANS_FAIL=plans_fail, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}", FAKE_LOG=str(self.log),
                   FAKE_REPO=str(self.repo.resolve()), SHELL=str(self.bin / "fakeshell"), TMUX="/tmp/x,1,0",
                   FAKE_WT=str(self.wt), FAKE_EXTRA=extra, FAKE_PAUSED=paused, HOME=str(self.home), PYTHONPATH=str(self.bin))
        return subprocess.run([sys.executable, str(HERE / "create.py"), "--repo", str(self.repo), *args],
                              capture_output=True, text=True, env=env)

    def run_call(self):
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return next(c for c in calls if c[1:3] == ["worktree", "run"])

    def test_the_first_slot_without_session_and_without_work(self):
        out = self.run_create()
        self.assertEqual((out["slot"], out["pane"], out["attach"]), ("06", "t:abc", "hal2-cli-agents attach app/06"))
        self.assertEqual([(s["slot"], s["why"]) for s in out["skipped"]],
                         [("03", "works on 0085-old"), ("04", "3 commits not on main"), ("05", "uncommitted changes")])
        run = self.run_call()
        self.assertEqual(run[3:7], ["06", "--agent", "claude", "--detach"])
        self.assertEqual(run[-1], "TMUX=")  # started outside this tmux pane
        self.assertEqual(run[run.index("--prompt") + 1], "/merge-from-main")

    def fake_overlap(self, answer: dict | None) -> None:
        """A `hal2-cli-plans` in the fake bin: `overlap` prints `answer` (None: exits 2, as an older CLI does)."""
        cli = self.bin / "hal2-cli-plans"
        cli.write_text("#!/bin/sh\nexit 2\n" if answer is None else
                       f"#!/bin/sh\n[ \"$1\" = overlap ] || exit 2\ncat <<'EOF'\n{json.dumps(answer)}\nEOF\n")
        cli.chmod(0o755)

    def overlap_prompt(self, answer, *args) -> tuple[dict, str]:
        self.fake_overlap(answer)
        r = self.run_raw("--prompt", "add reddit as a source", *args, overlap="on")
        self.assertEqual(r.returncode, 0, r.stderr)
        run = self.run_call()
        return json.loads(r.stdout), run[run.index("--prompt") + 1]

    def test_overlap_hits_go_into_the_first_prompt_to_settle(self):
        out, prompt = self.overlap_prompt({"plans": [{"slug": "0571-x", "title": "X", "field": "12", "state": "open",
                                                      "score": 0.8, "why": ["same words"], "path": "plans/0571-x/plan.md"}],
                                           "research": [], "text": TEXT})
        self.assertIn("Overlap with unfinished work (hal2-cli-plans overlap):\nCLI-REPORT", prompt)
        self.assertNotIn("Settle each hit", prompt)  # the CLI's report holds the hint, no copy here
        self.assertEqual(out["overlap"], ["CLI-LINE-1"])

    def test_an_overlap_resolved_prompt_stays_as_given(self):
        out, prompt = self.overlap_prompt({"plans": [], "research": [], "text": {**TEXT, "lines": []}})
        self.assertEqual(prompt, "Run /merge-from-main first, then:\n\nadd reddit as a source")
        self.assertEqual(out["overlap"], [])

    def test_a_missing_cli_says_unchecked_and_never_blocks(self):
        out, prompt = self.overlap_prompt(None)
        self.assertIn("overlap: overlap unchecked", prompt)
        self.assertEqual(out["overlap"], ["overlap unchecked"])

    def test_an_answer_without_text_is_unchecked(self):
        out, prompt = self.overlap_prompt({"plans": [{"slug": "0571-x"}], "research": []})
        self.assertIn("overlap: overlap unchecked", prompt)
        self.assertEqual(out["overlap"], ["overlap unchecked"])

    def test_no_overlap_skips_the_scan(self):
        out, prompt = self.overlap_prompt({"plans": [{"slug": "x"}], "research": []}, "--no-overlap")
        self.assertNotIn("Overlap", prompt)
        self.assertNotIn("overlap", out)

    def test_a_prompt_runs_after_mfm_unless_exact_and_flags_pass_through(self):
        self.run_create("--prompt", "/shoot 13", "--model", "m1", "--effort", "high", "--tmux")
        run = self.run_call()
        self.assertEqual(run[run.index("--effort") + 1], "high")
        self.assertEqual(run[run.index("--prompt") + 1], "Run /merge-from-main first, then:\n\n/shoot 13")
        self.assertEqual(run[run.index("--model") + 1], "m1")
        self.assertIn("--tmux", run)
        self.log.unlink()
        self.run_create("--prompt", "the shot", "--exact")
        run = self.run_call()
        self.assertEqual(run[run.index("--prompt") + 1], "the shot")

    def test_the_report_echoes_the_model_and_effort_asked_for(self):
        out = self.run_create("--model", "opus", "--effort", "medium")
        self.assertEqual((out["model"], out["effort"]), ("opus", "medium"))
        self.log.unlink()
        out = self.run_create()
        self.assertEqual((out["model"], out["effort"]), (None, None))  # the agent's own default

    def test_from_starts_the_search_at_the_slot(self):
        out = self.run_create("--from", "30")
        self.assertEqual((out["slot"], out["skipped"]), ("30", []))
        self.assertIn("--from needs a worktree from 00 to 99", self.refused("--from", "100"))
        self.assertIn("--from needs a worktree from 00 to 99", self.refused("--from", "x"))

    def test_to_ends_the_search_and_no_free_worktree_in_range_exits_3(self):
        """A range ends at --to; none free in it is exit 3, never a field above (plan 0333 step 9; since plan 0383 D16 the
        farmer's foremen search 00-99, so --to is for any caller that wants a smaller range)."""
        self.assertEqual(self.run_create("--from", "01", "--to", "29")["slot"], "06")
        r = self.run_raw("--from", "01", "--to", "05")
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertIn("no free and clean worktree from 01 to 05", r.stderr)
        self.assertIn("--to needs a worktree from 10 to 99", self.refused("--from", "10", "--to", "05"))
        self.assertIn("--to needs", self.refused("--to", "x"))

    def test_from_00_reaches_slot_00(self):
        """Plan 0270 (D13): the farmer's foremen start in the first free worktree from 00."""
        out = self.run_create("--from", "00", extra="00")
        self.assertEqual((out["slot"], out["skipped"]), ("00", []))
        self.assertEqual(self.run_call()[3], "00")
        self.assertEqual(self.run_create()["slot"], "06", "without --from the search still starts at 01")

    def test_a_reused_clean_slot_from_30_is_taken(self):
        out = self.run_create("--from", "30", "--min-free-gb", "999999999", extra="30")
        self.assertEqual(out["slot"], "30")  # an existing worktree needs no free disk

    def test_a_new_worktree_needs_free_disk(self):
        error = self.refused("--from", "30", "--min-free-gb", "999999999")

        self.assertIn("a new worktree needs 999999999 (--min-free-gb)", error)
        self.assertFalse(self.log.exists() and "run" in self.log.read_text())

    LEAD = "07 0376-one-plan-shape 02-readers"

    def test_base_is_gone(self):
        self.assertIn("--base is gone", self.refused("--from", "30", "--base", "x"))
        self.assertFalse(self.log.exists() and "run" in self.log.read_text())

    def test_lead_needs_a_servant_field_and_a_well_formed_line(self):
        self.assertIn("--lead needs --from 30", self.refused("--lead", self.LEAD))
        self.assertIn("--lead needs --from 30", self.refused("--from", "29", "--lead", self.LEAD))
        self.assertIn("--lead needs \"<field>", self.refused("--from", "30", "--lead", "07 0376 x"))
        self.assertIn("--lead needs \"<field>", self.refused("--from", "30", "--lead", "07 0376-one-plan-shape"))
        self.assertFalse(self.log.exists() and "run" in self.log.read_text())

    def assign_call(self):
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [c for c in calls if c[0] == "hal2-cli-plans"]

    def check_lead(self, line: str, steps: str):
        out = self.run_create("--from", "30", "--lead", line, "--model", "m", "--effort", "high", extra="30")
        self.assertEqual((out["slot"], out["lead"]), ("30", line))
        field, plan, _ = line.split()
        self.assertEqual(self.assign_call(), [["hal2-cli-plans", "servant", "assign", "30", "--plan", plan,
                                               "--steps", steps, "--repo", str(self.wt / field), "--json"]])
        self.assertFalse((self.wt / "30" / "plans" / "LEAD").exists(), "create.py writes no LEAD itself")
        run = self.run_call()
        prompt = run[run.index("--prompt") + 1]
        self.assertTrue(prompt.startswith("Run /merge-from-main first, then:"), prompt)
        self.assertIn("git merge origin/07", prompt)
        self.assertIn("run /servant", prompt)
        self.assertIn("servant status <step>", prompt)
        self.assertEqual(run[run.index("--model") + 1], "m")
        self.log.unlink()

    def test_lead_assigns_through_the_cli_for_a_sub_plan_a_legacy_row_and_a_step_list(self):
        self.check_lead(self.LEAD, "02-readers")
        self.check_lead("07 0376-one-plan-shape 5", "5")
        self.check_lead("07 0376-one-plan-shape 3,4,6", "3,4,6")

    def test_lead_in_a_missing_worktree_assigns_after_hal2_made_it(self):
        out = self.run_create("--from", "31", "--lead", self.LEAD)
        self.assertEqual(out["slot"], "31")
        self.assertEqual(self.assign_call()[0][3], "31")
        self.assertFalse((self.wt / "31" / "plans" / "LEAD").exists())

    def test_a_failing_assign_stops_the_start_with_its_message(self):
        r = self.run_raw("--from", "30", "--lead", self.LEAD, extra="30", plans_fail="1")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("servant assign failed: plan 0376 has no step 9", r.stderr)
        self.assertFalse(self.log.exists() and "run" in [c[1] for c in map(json.loads, self.log.read_text().splitlines())
                                                         if c[0] != "hal2-cli-plans" and len(c) > 1])

    def test_a_paused_field_is_skipped_and_named_in_the_skipped_list(self):
        r = self.run_raw(paused="06")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertNotEqual(out["slot"], "06")
        self.assertIn(("06", "paused by farmer: benchmark"), [(s["slot"], s["why"]) for s in out["skipped"]])

    def test_a_field_named_alone_that_is_paused_is_refused_with_the_reason(self):
        r = self.run_raw("--from", "06", "--to", "06", paused="06")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("field 06 is paused by farmer: benchmark", r.stderr)
        self.assertIn("worktree resume 06", r.stderr)
        self.assertFalse(self.log.exists() and "run" in self.log.read_text().replace("paused", ""))

    def test_an_older_cli_without_the_command_pauses_nothing(self):
        self.assertEqual(self.run_create()["slot"], "06")

if __name__ == "__main__":
    unittest.main()
