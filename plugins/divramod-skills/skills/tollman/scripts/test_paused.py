"""Hal2 plan 0458 step 3: the end-to-end proof that a paused field survives the tollman's tick. A field with a plan, a
handoff and commits not in the barn, and no session, is the orphan the tollman starts with `/handoff c` (hal2 plan 0412);
when hal2 says it is paused, the real `tollman.py tick` plans a record instead and `hal2-cli-git worktree run` is never
called. The control without the pause does start it, so the proof can fail.

`hal2-cli-git` and `hal2-cli-agents` are fakes on the PATH (the installed hal2-cli-git may predate `worktree paused`):
they answer from files and log every call; the tick, its planners, `tick.execute`, orphan_start.py and the git work run
for real, as separate processes where the tick starts them. No session, tmux, timer or merge queue is touched."""
# enforces .adr/paused-fields-never-woken.md (step 5 of the plan)

import json
import os
import stat
import sys
import textwrap
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import farmer
import mtm_scan
import tick
from test_tollman import Field

PAUSE = {"field": "07", "by": "farmer", "why": "reading its handoff", "since": "2026-10-28T09:00:00Z"}

GIT = f"""#!{sys.executable}
import json, os, sys
d = os.environ["FAKE_CLI_DIR"]
with open(os.path.join(d, "calls.log"), "a") as f:
    f.write(json.dumps(["hal2-cli-git"] + sys.argv[1:]) + "\\n")
a = sys.argv[1:]
if a[:2] == ["worktree", "paused"]:
    p = os.path.join(d, "paused.json")
    if not os.path.exists(p):
        sys.stderr.write("error: unknown command `paused`\\n")  # an older hal2-cli-git
        sys.exit(2)
    print(open(p).read())
elif a[:2] == ["worktree", "queue"]:
    print(json.dumps({{"queue": []}}))
elif a[:2] == ["worktree", "merge-from-main"]:
    print(json.dumps({{"status": "ok"}}))
elif a[:2] == ["worktree", "run"]:
    print(json.dumps({{"status": "started", "slot": a[2]}}))
"""
AGENTS = f"""#!{sys.executable}
import json, os, sys
d = os.environ["FAKE_CLI_DIR"]
with open(os.path.join(d, "calls.log"), "a") as f:
    f.write(json.dumps(["hal2-cli-agents"] + sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["list", "--json"]:
    print(json.dumps({{"agents": []}}))  # no session anywhere
"""


class Paused(Field):
    """A tollman tick on a scratch farm: field 07 holds a plan, its handoff and a commit, with no session."""

    def setUp(self):
        super().setUp()
        self.bin = self.tmp / "fakebin"
        self.bin.mkdir()
        for name, text in (("hal2-cli-git", GIT), ("hal2-cli-agents", AGENTS)):
            (self.bin / name).write_text(textwrap.dedent(text))
            (self.bin / name).chmod((self.bin / name).stat().st_mode | stat.S_IXUSR)
        self.calls_file = self.bin / "calls.log"
        self.calls_file.write_text("")
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "FAKE_CLI_DIR": str(self.bin)}
        def run_json(args, cwd=None):  # the farmer tests' Repo patches it out; here it asks the fake CLIs for real
            out = mtm_scan.run(args, cwd)
            return json.loads(out) if out.strip() else None

        for patch in (mock.patch.dict(os.environ, env), mock.patch.object(mtm_scan, "run_json", run_json)):
            patch.start()
            self.addCleanup(patch.stop)
        self.f07 = self.field("07")
        self.commit(self.f07, "plans/0458-x/handoff.md", "# handoff\n")
        self.commit(self.f07, "work.txt", "work\n")
        (self.f07 / "plans/CURRENT_PLAN").write_text("0458-x\n")
        self.assertEqual(self.call("mode", "timer"), (0, "timer\n"))

    def pause(self, *fields):
        (self.bin / "paused.json").write_text(json.dumps(
            {"schema": 1, "repo": "hal2", "fields": [{**PAUSE, "field": f} for f in fields]}))

    def calls(self):
        return [json.loads(x) for x in self.calls_file.read_text().splitlines()]

    def starts(self):
        return [c for c in self.calls() if c[:3] == ["hal2-cli-git", "worktree", "run"]
                or c[:2] == ["hal2-cli-agents", "send"] or "clear-and-continue" in c]

    def tick(self):
        code, out = self.call("tick")
        self.assertEqual(code, 0, out)
        return out

    def test_the_orphan_with_a_handoff_is_started_when_nothing_is_paused(self):
        self.pause()
        self.tick()
        self.assertEqual([c[3] for c in self.starts()], ["07"], self.calls())
        self.assertIn("/handoff c", self.starts()[0])
        self.assertIn("orphan", [e["kind"] for e in self.wm_log()])

    def test_a_paused_field_with_plan_and_handoff_survives_a_tick_with_no_session_started(self):
        self.pause("07")
        self.assertTrue((self.f07 / "plans/0458-x/handoff.md").is_file())
        out = self.tick()
        self.assertEqual(self.starts(), [], self.calls())
        self.assertIn(["hal2-cli-git", "worktree", "paused", "--json"], self.calls())
        log = self.wm_log()
        skipped = [e for e in log if e["kind"] == "paused-skip"]
        self.assertEqual([(e["slot"], e["do"], e["by"]) for e in skipped], [("07", "record", "tick")], out)
        self.assertEqual(skipped[0]["what"], "skipped run orphan: field 07 paused by farmer: reading its handoff")
        self.assertNotIn("orphan", [e["kind"] for e in log], "neither started nor woken for")
        self.assertEqual(self.wm_state_wakes(), [])
        # nothing of the field changed: plan, handoff and commits stay as they were
        self.assertEqual((self.f07 / "plans/CURRENT_PLAN").read_text(), "0458-x\n")

    def test_the_second_tick_adds_no_second_record_within_the_day(self):
        self.pause("07")
        self.tick()
        n = len([e for e in self.wm_log() if e["kind"] == "paused-skip"])
        with mock.patch.object(tick.due, "is_due", return_value=True):
            self.tick()
        self.assertEqual(len([e for e in self.wm_log() if e["kind"] == "paused-skip"]), n)
        self.assertEqual(self.starts(), [])

    def test_resumed_it_is_started_again(self):
        self.pause("07")
        self.tick()
        self.pause()
        with mock.patch.object(tick.due, "is_due", return_value=True), \
                mock.patch.object(tick, "fresh", lambda actions, *a, **k: actions):
            self.tick()
        self.assertEqual([c[3] for c in self.starts()], ["07"])

    def test_an_older_cli_without_the_command_pauses_nothing_and_the_round_goes_on(self):
        out = self.tick()  # no paused.json: the fake answers like the installed CLI, exit 2
        self.assertEqual([c[3] for c in self.starts()], ["07"], out)

    def test_another_field_s_pause_leaves_the_orphan_alone(self):
        self.pause("12")
        self.tick()
        self.assertEqual([c[3] for c in self.starts()], ["07"])

    def wm_state_wakes(self):
        """The wake items the tollman's model would be handed for field 07 (`tollman.py act`)."""
        code, out = self.call("act")
        return [line for line in out.splitlines() if " 07:" in line]


if __name__ == "__main__":
    unittest.main()
