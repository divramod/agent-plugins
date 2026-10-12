import json
import os
import time
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import evidence  # noqa: E402


class TranscriptTail(unittest.TestCase):
    def test_tools_denials_and_prompts(self):
        rows = [
            {"timestamp": "2026-09-30T10:14:35.922Z", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "git commit -m x"}}]}},
            {"timestamp": "2026-09-30T10:14:35.990Z", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "PreToolUse:Bash hook error: hal2: context at 36.2%"}]}},
            {"timestamp": "2026-09-30T10:14:35.990Z", "attachment": {
                "type": "hook_stopped_continuation", "message": "stopped for the hand-off"}},
            {"timestamp": "2026-09-30T10:14:37.245Z", "message": {"role": "user", "content": "hal2 stopped this turn"}},
            {"timestamp": "2026-09-30T10:14:38.000Z", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "plain output"}]}},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
        lines = evidence.transcript_tail(Path(f.name))
        self.assertEqual(len(lines), 4)
        self.assertIn("TOOL Bash", lines[0])
        self.assertIn("hook error", lines[1])
        self.assertIn("HOOK-STOP", lines[2])
        self.assertIn("hal2 stopped this turn", lines[3])


class Selfcheck(unittest.TestCase):
    def test_drift_is_reported(self):
        with tempfile.TemporaryDirectory() as repo:
            src = Path(repo) / evidence.SRC
            src.mkdir(parents=True)
            (src / "autoclear.rs").write_text('"waiting" REARM_POINTS MAX_ATTEMPTS DEFAULT_PROMPT')
            (src / "sweep.rs").write_text("pub const MAX_ATTEMPTS: u32 = 4;")
            skill = Path(repo) / "SKILL.md"
            skill.write_text(
                "`code/rust/libs/hal2-agents/src/autoclear.rs` `code/rust/libs/hal2-agents/src/gone.rs`\n"
                "<!-- names -->`waiting` `vanished-state`<!-- /names -->\n`REARM_POINTS` `HANDOFF_SCRIPTS`\n"
            )
            evidence.SKILL_MD = skill
            args = type("A", (), {"repo": repo})()
            out = []
            real_print = print
            try:
                evidence.print = lambda *a, **k: out.append(" ".join(map(str, a)))
                code = evidence.selfcheck(args)
            finally:
                evidence.print = real_print
            text = "\n".join(out)
            self.assertEqual(code, 1)
            self.assertIn("gone.rs", text)
            self.assertIn("vanished-state", text)
            self.assertIn("HANDOFF_SCRIPTS", text)
            self.assertIn("MAX_ATTEMPTS is 4", text)
            self.assertNotIn("DRIFT name `waiting`", text)


# hal2 wt 02, 2026-10-06 (skills plan 0011): the user's "disable the autoclear in 02", written by hand as this marker;
# the farmer's autoclear duty took it for a give-up and ran clear-and-continue (job 171, cancelled by 02).
OFF_227 = {"session_id": "227f49f1-0b95-4ea0-af2f-b55a9b6a9917", "pane": "%171", "stage": "cancelled", "percent": 22.0,
           "threshold": 35, "soft_at": 1791272539541, "rearm_percent": 1000.0, "gave_up": True}
JOB_171 = {"state": "cancelled", "pane": "%171", "old_session": "227f49f1-0b95-4ea0-af2f-b55a9b6a9917",
           "prompt": "/handoff c", "requested_at": 1791274202629, "updated_at": 1791274355223, "pid": 78211}
# The sweep's own give-up (hal2 sweep.rs, MAX_ATTEMPTS): a real failure the doctor must keep reporting.
SWEEP_GAVE_UP = {"session_id": "4100c537-6070-4262-b6cd-aabe0fb0067c", "pane": "%49", "stage": "soft", "percent": 35.0,
                 "threshold": 35, "soft_at": 1791014836027, "denied_tool": "Bash", "attempts": 3, "gave_up": True}


class AutoclearOff(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.jobs, self.real = Path(self.dir.name), (evidence.JOBS, evidence.agents, evidence.session_label)
        evidence.JOBS = self.jobs
        evidence.agents = lambda: [{"pane_id": "%171", "kind": "claude", "project": "/a/hal2", "slot": "02",
                                    "session_id": OFF_227["session_id"], "state": "idle"}]
        evidence.session_label = lambda session: None

    def tearDown(self):
        evidence.JOBS, evidence.agents, evidence.session_label = self.real
        self.dir.cleanup()

    def write(self, name, data):
        (self.jobs / name).write_text(json.dumps(data))

    def test_a_marker_only_a_hand_wrote_is_off_the_sweeps_give_up_is_not(self):
        self.assertTrue(evidence.autoclear_off(OFF_227))
        self.assertTrue(evidence.autoclear_off({**OFF_227, "gave_up": False}))  # rearm 1000: never re-arms
        self.assertTrue(evidence.autoclear_off({"gave_up": True}))
        self.assertFalse(evidence.autoclear_off(SWEEP_GAVE_UP))
        self.assertFalse(evidence.autoclear_off({"stage": "cancelled", "percent": 41.2, "threshold": 35,
                                                 "rearm_percent": 46.2}))  # hal2's own cancel re-arms
        self.assertFalse(evidence.autoclear_off({"attempts": 2}))
        self.assertTrue(evidence.autoclear_off(agent={"autoclear_off": True}))  # hal2 shot plugin-agents #31

    def test_the_doctor_replays_227f49f1_and_reports_only_the_sweeps_give_up(self):
        self.write(f"{OFF_227['session_id']}.guard", OFF_227)
        self.write(f"{SWEEP_GAVE_UP['session_id']}.guard", SWEEP_GAVE_UP)
        self.write("171.json", {**JOB_171, "state": "failed", "reason": "attempts"})
        off = []
        problems = evidence.doctor_items(24, off)
        self.assertEqual([p["session"] for p in problems], [SWEEP_GAVE_UP["session_id"]])
        self.assertEqual([o["session"] for o in off], [OFF_227["session_id"]])

    def test_an_agent_switched_off_by_hal2_is_no_problem(self):
        evidence.agents = lambda: [{"pane_id": "%49", "session_id": SWEEP_GAVE_UP["session_id"],
                                    "autoclear_off": True}]
        self.write(f"{SWEEP_GAVE_UP['session_id']}.guard", SWEEP_GAVE_UP)
        self.assertEqual(evidence.doctor_items(24), [])


# hal2 wt 02, 2026-10-06 17:55 (hal2 plan 0174): the weekly usage limit ended the turn, the session's process ended
# with the tmux restart; the job's `session-ended` was right and hal2 reports no such reason, but the doctor listed
# it and the farmer's autoclear duty delegated it.
JOB_ENDED = {"state": "failed", "reason": "session-ended", "message": "the session ended", "pane": "%171",
             "old_session": "5f157c8c-0000-4000-8000-000000000000", "prompt": "/handoff c"}


class Quiet(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.jobs = Path(self.dir.name)
        self.real = (evidence.JOBS, evidence.agents, evidence.session_label, evidence.markers)
        evidence.JOBS, evidence.agents = self.jobs, lambda: []
        evidence.session_label, evidence.markers = lambda session: "hal2 wt 02", lambda: []

    def tearDown(self):
        evidence.JOBS, evidence.agents, evidence.session_label, evidence.markers = self.real
        self.dir.cleanup()

    def test_a_session_that_ended_on_its_own_is_no_problem(self):
        (self.jobs / "171.json").write_text(json.dumps(JOB_ENDED))
        (self.jobs / "54.json").write_text(json.dumps(
            {"state": "failed", "reason": "typing-mismatch", "pane": "%54", "old_session": "s1"}))
        quiet = []
        problems = evidence.doctor_items(24, quiet=quiet)
        self.assertEqual([(p["pane"], p["reason"]) for p in problems], [("%54", "typing-mismatch")])
        self.assertEqual([(q["who"], q["pane"], q["reason"]) for q in quiet],
                         [("hal2 wt 02", "%171", "session-ended")])
        self.assertEqual(len(evidence.doctor_items(24)), 1)  # what the farmer's duty calls: no list to collect

    def test_every_reason_hal2_does_not_report_is_quiet_and_only_when_failed(self):
        for n, reason in enumerate(sorted(evidence.QUIET)):
            (self.jobs / f"{n}.json").write_text(json.dumps({**JOB_ENDED, "pane": f"%{n}", "reason": reason}))
        # A job stuck in `waiting` for over 30 min stays a problem whatever its record's reason says.
        stuck = self.jobs / "9.json"
        stuck.write_text(json.dumps({**JOB_ENDED, "pane": "%9", "state": "waiting"}))
        old = time.time() - 3600
        os.utime(stuck, (old, old))
        quiet = []
        problems = evidence.doctor_items(24, quiet=quiet)
        self.assertEqual([p["pane"] for p in problems], ["%9"])
        self.assertEqual(sorted(q["reason"] for q in quiet), sorted(evidence.QUIET))

    def test_the_doctor_prints_them_apart(self):
        (self.jobs / "171.json").write_text(json.dumps(JOB_ENDED))
        out, real_print = [], print
        try:
            evidence.print = lambda *a, **k: out.append(" ".join(map(str, a)))
            evidence.doctor(type("A", (), {"hours": 24, "json": False})())
            evidence.doctor(type("A", (), {"hours": 24, "json": True})())
        finally:
            evidence.print = real_print
        self.assertEqual(out[0], "0 problem(s) in the last 24 h; ended on their own (not reported by hal2): "
                                 "hal2 wt 02 session-ended")
        data = json.loads(out[1])
        self.assertEqual((data["problems"], [q["reason"] for q in data["quiet"]]), ([], ["session-ended"]))

    def test_selfcheck_compares_the_quiet_reasons_with_hal2s_report(self):
        with tempfile.TemporaryDirectory() as repo:
            src = Path(repo) / evidence.SRC
            src.mkdir(parents=True)
            (src / "report.rs").write_text("FailReason::AgentGone | FailReason::SessionEnded | FailReason::AlreadyRunning")
            skill = Path(repo) / "SKILL.md"
            skill.write_text("nothing to check\n")
            real_skill, real_print, out = evidence.SKILL_MD, print, []
            try:
                evidence.SKILL_MD = skill
                evidence.print = lambda *a, **k: out.append(" ".join(map(str, a)))
                evidence.selfcheck(type("A", (), {"repo": repo})())
            finally:
                evidence.SKILL_MD, evidence.print = real_skill, real_print
            drift = [line for line in out if "QUIET" in line]
            self.assertEqual(len(drift), 1)
            self.assertIn("FailReason::InvalidRequest", drift[0])


if __name__ == "__main__":
    unittest.main()


class Labels(unittest.TestCase):
    AGENTS = [
        {"pane_id": "%1", "kind": "claude", "project": "/a/hal2", "slot": "02"},
        {"pane_id": "%2", "kind": "codex", "project": "/a/hal2", "slot": "03"},
        {"pane_id": "%3", "kind": "claude", "project": "/a/other", "slot": "02"},
        {"pane_id": "%4", "kind": "claude", "project": "/a/hal2", "slot": "main"},
    ]

    def test_agents_are_named_by_repo_and_worktree(self):
        self.assertEqual(evidence.label("/a/hal2", "02"), "hal2 wt 02")
        self.assertEqual(evidence.label("/a/hal2", "main"), "hal2 main")
        self.assertEqual(evidence.agent_label(self.AGENTS[0]), "hal2 wt 02")
        self.assertEqual(evidence.agent_label({"pane_id": "%9"}), "the agent in pane %9")

    def test_a_worktree_finds_its_claude_agent(self):
        agent, many = evidence.find_agent(self.AGENTS, "02", "hal2")
        self.assertEqual((agent["pane_id"], many), ("%1", []))
        agent, many = evidence.find_agent(self.AGENTS, "02")
        self.assertIsNone(agent)
        self.assertEqual(many, ["hal2 wt 02", "other wt 02"])
        self.assertEqual(evidence.find_agent(self.AGENTS, "03", "hal2"), (None, []))
        self.assertEqual(evidence.find_agent(self.AGENTS, "main", "hal2")[0]["pane_id"], "%4")

    def test_show_resolves_a_worktree_of_this_repo_first(self):
        real_agents, real_repo = evidence.agents, evidence.current_repo
        try:
            evidence.agents = lambda: self.AGENTS
            evidence.current_repo = lambda: "hal2"
            args = type("A", (), {"pane": None, "session": None, "worktree": "02", "repo": None})()
            pane, agent, problem = evidence.resolve_pane(args)
            self.assertEqual((pane, problem), ("%1", None))
            evidence.current_repo = lambda: None
            pane, agent, problem = evidence.resolve_pane(args)
            self.assertIsNone(pane)
            self.assertIn("hal2 wt 02, other wt 02", problem)
        finally:
            evidence.agents, evidence.current_repo = real_agents, real_repo


class Capture(unittest.TestCase):
    def test_doctor_lists_a_job_blocked_by_a_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp)
            now = int(time.time() * 1000)
            (jobs / "12.json").write_text(json.dumps(
                {"state": "waiting", "pane": "t:abc", "old_session": "s1", "waiting_on": "draft",
                 "waiting_since": now - 4 * 60_000, "updated_at": now}))
            (jobs / "13.json").write_text(json.dumps(
                {"state": "waiting", "pane": "%13", "old_session": "s2", "waiting_on": "draft",
                 "waiting_since": now - 60_000, "updated_at": now}))
            saved = (evidence.JOBS, evidence.agents, evidence.markers)
            try:
                evidence.JOBS, evidence.agents, evidence.markers = jobs, lambda: [], lambda: []
                items = evidence.doctor_items(1)
            finally:
                evidence.JOBS, evidence.agents, evidence.markers = saved
            self.assertEqual([(i["what"], i["pane"], i["reason"]) for i in items],
                             [("blocked", "t:abc", "continue-blocked")])
            self.assertIn("a draft in the input box since", items[0]["message"])

    def test_an_incident_becomes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            jobs = tmp / "state/agents/autoclear"
            jobs.mkdir(parents=True)
            (jobs / "54.json").write_text(json.dumps(
                {"state": "failed", "reason": "clear-unconfirmed", "pane": "%54", "old_session": "s1"}))
            (jobs / "54.log").write_text("2026-09-30 10:00:00 clearing\n")
            (jobs / "s1.guard").write_text(json.dumps({"session_id": "s1", "pane": "%54", "stage": "soft"}))
            (jobs / "sweep.log").write_text("2026-09-30 10:00:01   %54 02 s1 context 40% state done plan x: skip\n"
                                            "2026-09-30 10:00:01   %9 03 s9 context 1% state done plan x: skip\n")
            agent = {"pane_id": "%54", "kind": "claude", "project": "/a/hal2", "slot": "02", "session_id": "s1"}
            saved = (evidence.JOBS, evidence.agents, evidence.screen, evidence.current_repo, evidence.need)
            try:
                evidence.JOBS = jobs
                evidence.agents = lambda: [agent]
                evidence.screen = lambda pane: "❯ /clear\n  ─── History 96/100 ───"
                evidence.current_repo = lambda: "hal2"
                evidence.need = lambda tool: None
                args = type("A", (), {"pane": None, "session": None, "worktree": "02", "repo": None,
                                      "out": str(tmp / "out"), "hours": 1e6})()
                self.assertEqual(evidence.capture(args), 0)
            finally:
                evidence.JOBS, evidence.agents, evidence.screen, evidence.current_repo, evidence.need = saved
            out = tmp / "out"
            self.assertIn("History 96/100", (out / "screen.txt").read_text())
            self.assertEqual(json.loads((out / "job.json").read_text())["reason"], "clear-unconfirmed")
            self.assertTrue((out / "job.log").exists() and (out / "marker-s1.json").exists())
            sweep = (out / "sweep.log").read_text()
            self.assertIn("%54", sweep)
            self.assertNotIn("%9 ", sweep)
            readme = (out / "README.md").read_text()
            self.assertIn("hal2 wt 02", readme)
            self.assertIn("src/fixtures/screens", readme)
