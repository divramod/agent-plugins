import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import scan  # noqa: E402

PROJECT = "/p/hal2"
NOW = 1_790_770_000_000
MIN = scan.MINUTE


def agent(slot="01", state="failed", session="s1", since=NOW - 5 * MIN, **extra):
    return {"pane_id": f"%{slot}", "slot": slot, "project": PROJECT, "checkout": f"/w/{slot}", "state": state,
            "session_id": session, "since": since, "source": "hook", "plan": "0075 · x", "autoclear": None,
            **extra}


def tail(error=None, text="", prompt_ms=0, question=False, assistant="done with step 3"):
    return {"api_error": {"error": error, "text": text, "ms": 0} if error else None, "last_prompt_ms": prompt_ms,
            "last_prompt": "", "last_assistant": assistant, "question_pending": question}


def failed_event(session="s1", ts=NOW - 5 * MIN):
    return {"ts": ts, "session": session, "agent": "claude", "pane": "%01", "state": "failed", "cwd": "/w/01"}


class Classify(unittest.TestCase):
    def test_classes(self):
        cases = {
            ("server_error", "API Error: Connection lost mid-response. The response above may be incomplete."): "F1",
            ("overloaded", "API Error: 529 overloaded"): "F1",
            ("server_error", "API Error: Can't reach the API server — check your internet or DNS (ENOTFOUND)"): "F2",
            ("server_error", "API Error: Your computer went to sleep mid-response."): "F3",
            ("rate_limit", "You've hit your session limit · resets 3pm"): "F4",
            ("billing_error", "Credit balance is too low"): "F5",
            ("", "something new"): "F12",
        }
        for (error, text), cls in cases.items():
            self.assertEqual(scan.classify_api_error(error, text), cls, text)


class TranscriptTail(unittest.TestCase):
    def test_api_error_prompts_and_questions(self):
        rows = [
            {"type": "user", "timestamp": "2026-09-30T10:00:00Z", "message": {"content": "<local-command-caveat>x"}},
            {"type": "user", "timestamp": "2026-09-30T10:00:01Z",
             "message": {"content": "<command-name>/plan</command-name><command-args>n</command-args>"}},
            {"type": "assistant", "timestamp": "2026-09-30T10:05:00Z",
             "message": {"content": [{"type": "text", "text": "Next, hal2-api."}]}},
            {"type": "assistant", "timestamp": "2026-09-30T10:06:00Z", "isApiErrorMessage": True,
             "error": "server_error",
             "message": {"content": [{"type": "text", "text": "API Error: Connection lost mid-response."}]}},
            {"type": "assistant", "isSidechain": True, "isApiErrorMessage": True, "error": "x",
             "message": {"content": []}},
        ]
        result = scan.transcript_tail(json.dumps(r) for r in rows)
        self.assertEqual(result["api_error"]["error"], "server_error")
        self.assertIn("Connection lost", result["api_error"]["text"])
        self.assertEqual(result["last_prompt_ms"], scan._ms("2026-09-30T10:00:01Z"))
        self.assertEqual(result["last_assistant"], "Next, hal2-api.")
        self.assertFalse(result["question_pending"])

    def test_question_pending_until_answered(self):
        ask = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "AskUserQuestion"}]}}
        self.assertTrue(scan.transcript_tail([json.dumps(ask)])["question_pending"])
        answer = {"type": "user", "message": {"content": "yes"}}
        self.assertFalse(scan.transcript_tail([json.dumps(ask), json.dumps(answer)])["question_pending"])


class FindIncidents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        scan.RECORDS = Path(self.tmp.name)
        self.state = {"handled": {}, "resumes": {}}

    def tearDown(self):
        self.tmp.cleanup()

    def find(self, agents, events=(), tails=None, plan=None, moved=None):
        return scan.find_incidents(PROJECT, agents, list(events), [], self.state, NOW,
                                   tails=lambda s: (tails or {}).get(s, tail()), plan_of=lambda c: plan,
                                   moved=lambda s, t: (moved or {}).get(t))

    def test_connection_lost_is_resumed(self):
        [found] = self.find([agent()], [failed_event()],
                            {"s1": tail("server_error", "API Error: Connection lost mid-response.")})
        self.assertEqual((found["class"], found["action"], found["pane"]), ("F1", "resume", "%01"))

    def test_resumed_by_the_user_is_only_counted(self):
        events = [failed_event(), {**failed_event(), "state": "working", "ts": NOW - 4 * MIN}]
        [found] = self.find([agent(state="working")], events,
                            {"s1": tail("server_error", "Connection lost", prompt_ms=NOW - 4 * MIN)})
        self.assertEqual(found["action"], "count")
        self.assertIn("resolved by user", found["reason"])

    def test_resume_budget_escalates(self):
        self.state["resumes"]["s1"] = [NOW - 60 * MIN, NOW - 30 * MIN]
        [found] = self.find([agent()], [failed_event()], {"s1": tail("server_error", "Connection lost")})
        self.assertEqual(found["action"], "escalate")
        self.assertEqual(scan.resumes_left({"resumes": {"s1": [NOW - 7 * 60 * MIN]}}, "s1", NOW), 2)

    def test_billing_is_escalated(self):
        [found] = self.find([agent()], [failed_event()], {"s1": tail("billing_error", "Credit balance is too low")})
        self.assertEqual((found["class"], found["action"]), ("F5", "escalate"))

    def test_other_projects_are_ignored(self):
        other = agent()
        other["project"] = "/p/other"
        self.assertEqual(self.find([other], [failed_event()]), [])

    def test_early_end_in_a_plan_is_judged(self):
        plan = {"slug": "0073-x", "land": "wait", "next": {"number": "6", "step": "the last one"}}
        [found] = self.find([agent(state="done", since=NOW - 15 * MIN)], plan=plan)
        self.assertEqual((found["class"], found["action"]), ("F6", "judge"))
        self.assertEqual(found["evidence"]["next_step"], "6: the last one")

    def test_no_early_end_when_asking_recent_or_landing(self):
        plan = {"slug": "0073-x", "land": "wait", "next": {"number": "6", "step": "s"}}
        self.assertEqual(self.find([agent(state="done", since=NOW - 15 * MIN)], plan=plan,
                                   tails={"s1": tail(question=True)}), [])
        self.assertEqual(self.find([agent(state="done", since=NOW - 3 * MIN)], plan=plan), [])
        self.assertEqual(self.find([agent(state="done", since=NOW - 15 * MIN)],
                                   plan={**plan, "land": "ready"}), [])
        busy = agent(state="done", since=NOW - 15 * MIN, autoclear={"state": "waiting"})
        self.assertEqual(self.find([busy], plan=plan), [])

    def test_a_coordinator_waiting_on_its_background_work_is_left_alone(self):
        plan = {"slug": "0016-x", "land": "wait", "next": {"number": "8", "step": "s"}}
        resting = dict(state="done", since=NOW - 30 * MIN)
        sub = {"id": "a1", "type": "subagent", "description": "Plan 0016 row 8: s"}
        shell = {"id": "b1", "type": "shell", "description": "watch"}
        self.assertEqual(self.find([agent(**resting, background_tasks=[sub])], plan=plan,
                                   moved={"a1": NOW - 2 * MIN}), [])
        self.assertEqual(self.find([agent(**resting, background_tasks=[shell])], plan=plan), [])
        self.assertEqual(self.find([agent(**resting, background_tasks=[sub])], plan=plan), [])  # no transcript yet
        # one live task is enough, even beside a dead subagent
        dead = {"id": "a2", "type": "subagent", "description": "Plan 0016 row 7: s"}
        self.assertEqual(self.find([agent(**resting, background_tasks=[sub, dead])], plan=plan,
                                   moved={"a1": NOW - 2 * MIN, "a2": NOW - 50 * MIN}), [])

    def test_a_dead_subagent_under_an_idle_parent_is_judged(self):
        dead = {"id": "a2", "type": "subagent", "description": "Plan 0016 row 7: s"}
        [found] = self.find([agent(state="sleeping", since=NOW - 30 * MIN, background_tasks=[dead])],
                            moved={"a2": NOW - 25 * MIN})
        self.assertEqual((found["class"], found["action"], found["name"]),
                         ("F14", "judge", "subagent dead under an idle parent"))
        self.assertEqual((found["evidence"]["subagents"][0]["id"], found["evidence"]["subagents"][0]["quiet_minutes"]),
                         ("a2", 25))
        self.assertEqual(self.find([agent(state="sleeping", since=NOW - 5 * MIN, background_tasks=[dead])],
                                   moved={"a2": NOW - 25 * MIN}), [])

    def test_an_agent_call_whose_subagent_moves_is_no_hang(self):
        (scan.RECORDS / "s1.json").write_text(json.dumps({"event": "PreToolUse", "detail": "Agent",
                                                         "ts": NOW - 90 * MIN}))
        self.assertEqual(self.find([agent(state="working")], moved={None: NOW - 5 * MIN}), [])
        [found] = self.find([agent(state="working")], moved={None: NOW - 70 * MIN})
        self.assertEqual((found["class"], found["evidence"]["quiet_minutes"]), ("F7", 70))

    def test_subagent_moved_reads_the_subagent_transcripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, scan.PROJECTS = scan.PROJECTS, Path(tmp)
            try:
                folder = Path(tmp, "-p", "s1", "subagents")
                folder.mkdir(parents=True)
                (folder / "agent-a1.jsonl").write_text("{}\n")
                self.assertIsNotNone(scan.subagent_moved("s1", "a1"))
                self.assertIsNotNone(scan.subagent_moved("s1"))
                self.assertIsNone(scan.subagent_moved("s1", "a9"))
            finally:
                scan.PROJECTS = old

    def test_hang_and_long_tool_call(self):
        (scan.RECORDS / "s1.json").write_text(json.dumps({"event": "PostToolUse", "ts": NOW - 25 * MIN}))
        [found] = self.find([agent(state="working")])
        self.assertEqual((found["class"], found["evidence"]["quiet_minutes"]), ("F7", 25))
        (scan.RECORDS / "s1.json").write_text(json.dumps({"event": "PreToolUse", "ts": NOW - 25 * MIN}))
        self.assertEqual(self.find([agent(state="working")]), [])

    def test_dialog_waiting_and_failed_autoclear(self):
        [found] = self.find([agent(state="blocked-permission", since=NOW - 40 * MIN)])
        self.assertEqual((found["class"], found["action"]), ("F9", "escalate"))
        [found] = self.find([agent(state="done", autoclear={"state": "failed", "updated_at": NOW})])
        self.assertEqual((found["class"], found["action"]), ("F11", "handover"))

    def test_continue_blocked_by_a_draft(self):
        job = {"state": "waiting", "waiting_on": "draft", "waiting_since": NOW - 4 * MIN}
        [found] = self.find([agent(state="done", autoclear=job)])
        self.assertEqual((found["class"], found["action"], found["name"]), ("F13", "judge", "continue blocked"))
        self.assertEqual((found["at"], found["evidence"]["waiting_minutes"]), (NOW - 4 * MIN, 4))
        self.assertEqual(self.find([agent(state="done", autoclear={**job, "waiting_since": NOW - 2 * MIN})]), [])
        self.assertEqual(self.find([agent(state="done", autoclear={"state": "waiting"})]), [])


class Record(unittest.TestCase):
    def test_record_counts_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan.DATA = Path(tmp)
            scan.main(["record", "F1:s9:1", "resume"])
            scan.main(["record", "F1:s9:2", "resume"])
            state = scan.load_state()
            self.assertEqual(len(state["resumes"]["s9"]), 2)
            self.assertEqual(scan.resumes_left(state, "s9", scan.now_ms()), 0)
            self.assertEqual(len((Path(tmp) / "log.jsonl").read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
