import datetime as dt
import unittest

import duties
import tick

NOW = dt.datetime(2026, 10, 3, 10, 0)


def ctx(**kw):
    return {"top": "/x/farmer", "main": "/x/hal2", "now": NOW, "log": [], "duties": {"mtm", "lead"},
            "panes": {"04": "%4", "05": "%5"}, "agents_by_pane": {}, "landing": set(), **kw}


def kinds(actions, log=()):
    return [(a["do"], a["kind"], a["slot"]) for a in tick.fresh(actions, list(log), NOW)]


def helper(kind, said="", **kw):
    return {"kind": kind, "slot": "04", "pane": "%4", "session": "s1", "since": 1, "said": said, "why": "w", **kw}


class Lead(unittest.TestCase):
    def plan(self, *needs, **kw):
        return duties.plan_lead({}, ctx(**kw), {"needs_help": list(needs)})

    def test_templated_help_is_sent_and_marked_handled(self):
        for kind in ("no-plan", "context-high"):
            self.assertEqual(kinds(self.plan(helper(kind))), [("send", kind, "04"), ("run", "handled", "04")])

    def test_a_stop_announcing_the_next_step_gets_continue_a_wait_wakes(self):
        going = helper("idle-in-plan", "Step 2 is done.\n\nNext I'll write the tests.")
        self.assertEqual(kinds(self.plan(going))[0], ("send", "idle-in-plan", "04"))
        waiting = helper("idle-in-plan", "Next I'll continue once the queue returns.")
        self.assertEqual(kinds(self.plan(waiting)), [("wake", "idle-in-plan", "04")])

    def test_a_subservant_stopped_mid_step_hands_its_step_to_the_lead_never_lands(self):
        # Skills plan 0013: a slot with plans/LEAD never lands; skills plan 0016: `plan.py report` is gone, so the text
        # says what plan.py's refusal says (the lead takes the work over, or plans/LEAD is deleted).
        lead = {"slot": "02", "plan": "0149-hal9k", "step": "7"}
        going = helper("idle-in-plan", "Tests written.\n\nNext I'll run the gate.", slot="31", lead=lead)
        planned = self.plan(going)
        self.assertEqual(kinds(planned), [("send", "idle-in-plan", "31"), ("run", "handled", "31")])
        text = planned[0]["text"]
        for part in ("step 7 of plan 0149-hal9k", "slot 02", "the lead in slot 02 takes the work over",
                     "delete plans/LEAD", "never land"):
            self.assertIn(part, text)
        self.assertNotIn("plan.py report", text)
        self.assertNotIn("/mtm", text)
        self.assertNotIn("plan to its end", text)
        waiting = helper("idle-in-plan", "Next I'll continue once the lead answers.", slot="31", lead=lead)
        self.assertEqual(kinds(self.plan(waiting)), [("wake", "idle-in-plan", "31")])

    def test_a_subservant_with_a_broken_marker_is_judged_never_told_to_continue_the_plan(self):
        # Review 1 finding 10: bad but marked, no step to continue.
        bad = {"bad": True, "text": "x", "error": "plans/LEAD is not `<lead-slot> <plan> <step>`: 'x'"}
        going = helper("idle-in-plan", "Tests written.\n\nNext I'll run the gate.", slot="31", lead=bad)
        self.assertEqual(kinds(self.plan(going)), [("wake", "idle-in-plan", "31")])

    def test_the_farmers_own_session_is_never_told_or_woken_about(self):
        self.assertEqual(kinds(self.plan(helper("asks", slot="farmer"), helper("no-plan", slot="farmer"))),
                         [])

    def test_questions_and_blocks_wake_failed_goes_to_watch_when_on(self):
        self.assertEqual(kinds(self.plan(helper("asks"), helper("blocked"))),
                         [("wake", "asks", "04"), ("wake", "blocked", "04")])
        self.assertEqual(kinds(self.plan(helper("failed")))[0], ("send", "failed", "04"))
        self.assertEqual(kinds(self.plan(helper("failed"), duties={"watch"})), [("wake", "failed", "04")])

    def test_slots_the_boss_told_this_round_are_skipped_and_handled_stops_not_repeated(self):
        self.assertEqual(self.plan(helper("no-plan"), told={"04"}), [])
        self.assertEqual(kinds(self.plan(helper("no-plan")), [{"at": NOW.isoformat(), "key": "lead:s1:1"}]), [])


def red(kind="main-red", branch="main"):
    return {"kind": kind, "run": 9, "workflow": "ci", "branch": branch, "url": "u", "why": "ci failure on main",
            "failed_jobs": ["test"]}


class Ci(unittest.TestCase):
    def test_transient_main_red_reruns_once_a_real_one_is_delegated(self):
        rerun = duties.plan_ci({}, ctx(), {"findings": [red()]}, lambda run: "x\ncurl: ECONNRESET\n")
        self.assertEqual(kinds(rerun), [("run", "rerun", "-"), ("run", "handled", "-")])
        self.assertEqual(rerun[0]["argv"], ["gh", "run", "rerun", "9", "--failed"])
        real = duties.plan_ci({}, ctx(), {"findings": [red()]}, lambda run: "assert 1 == 2")
        self.assertEqual(kinds(real), [("delegate", "main-red", "-")])

    def test_a_red_slot_is_told_runners_wake(self):
        plan = duties.plan_ci({}, ctx(), {"findings": [red("slot-red", "05"), red("queued-long", "main")]})
        self.assertEqual(kinds(plan), [("send", "slot-red", "05"), ("run", "handled", "05"), ("wake", "queued-long", "main")])


    def test_a_long_queued_job_runs_the_wake_tool(self):
        wake = {**red("queued-wake", "land/12"), "tool": "/r/code/bash/scripts/ci-wake/main.sh"}
        plan = duties.plan_ci({}, ctx(), {"findings": [wake]})
        self.assertEqual(kinds(plan), [("run", "queued-wake", "-")])
        self.assertEqual(plan[0]["argv"], ["bash", "/r/code/bash/scripts/ci-wake/main.sh", "start"])
        self.assertEqual(plan[0]["window"], 600)

def incident(action, cls="F1", **kw):
    return {"id": f"{cls}:s1:t", "class": cls, "name": "n", "session": "s1", "slot": "04", "pane": "%4",
            "action": action, "reason": "", "evidence": {"api_error": {"text": "Connection lost"}}, **kw}


class Watch(unittest.TestCase):
    def test_resume_count_escalate_wait_judge(self):
        found = [incident("resume"), incident("count"), incident("escalate"), incident("wait"), incident("judge", "F6")]
        self.assertEqual(kinds(duties.plan_watch({}, ctx(), found)),
                         [("send", "resume", "04"), ("run", "handled", "04"), ("run", "handled", "04"),
                          ("notify", "escalate", "04"), ("run", "handled", "04"), ("wake", "judge", "04")])
        self.assertIn("Connection lost", duties.plan_watch({}, ctx(), found[:1])[0]["text"])

    def test_never_a_resume_into_a_landing(self):
        self.assertEqual(kinds(duties.plan_watch({}, ctx(landing={"04"}), [incident("resume")])), [("wake", "resume", "04")])


class Autoclear(unittest.TestCase):
    def test_the_same_resting_session_is_continued_and_every_class_delegated_once(self):
        p = {"what": "job", "pane": "%4", "session": "s1", "who": "hal2 wt 04", "reason": "ignored-soft-stop",
             "message": "m"}
        agents = {"%4": {"slot": "04", "session_id": "s1", "state": "done"}}
        plan = duties.plan_autoclear({}, ctx(agents_by_pane=agents), [p], set())
        self.assertEqual(kinds(plan), [("run", "continue", "04"), ("delegate", "fix", "04")])
        moved = {"%4": {"slot": "04", "session_id": "s2", "state": "done"}}
        log = [{"at": NOW.isoformat(), "key": "autoclear-fix:ignored-soft-stop"}]
        self.assertEqual(kinds(duties.plan_autoclear({}, ctx(agents_by_pane=moved), [p], set()), log), [])


    def test_a_job_blocked_by_a_draft_is_left_to_sanity_watch(self):
        p = {"what": "blocked", "pane": "%4", "session": "s1", "who": "hal2 wt 04", "reason": "continue-blocked",
             "message": "a draft in the input box since 08:15"}
        agents = {"%4": {"slot": "04", "session_id": "s1", "state": "done"}}
        self.assertEqual(duties.plan_autoclear({}, ctx(agents_by_pane=agents), [p], set()), [])

    def test_a_session_the_user_switched_off_is_never_cleared_or_delegated(self):
        # hal2 wt 02, 2026-10-06 (plan 0011): the user's "disable the autoclear in 02" as a hand-written marker; the
        # doctor took it for a give-up, this duty ran clear-and-continue on the idle session (job 171).
        marker = {"session_id": "227f49f1-0b95-4ea0-af2f-b55a9b6a9917", "pane": "%171", "stage": "cancelled",
                  "percent": 22.0, "threshold": 35, "soft_at": 1791272539541, "rearm_percent": 1000.0, "gave_up": True}
        p = {"what": "marker", "pane": "%171", "session": marker["session_id"], "who": "hal2 wt 02", "attempts": 0,
             "gave_up": True}
        agents = {"%171": {"slot": "02", "session_id": marker["session_id"], "state": "idle"}}
        self.assertTrue(duties.evidence.autoclear_off(marker))
        self.assertEqual(duties.plan_autoclear({}, ctx(agents_by_pane=agents), [p], {marker["session_id"]}), [])
        switched = {"%171": {**agents["%171"], "autoclear_off": True}}
        self.assertEqual(duties.plan_autoclear({}, ctx(agents_by_pane=switched), [p], set()), [])
        self.assertEqual(kinds(duties.plan_autoclear({}, ctx(agents_by_pane=agents), [p], set())),
                         [("run", "continue", "02"), ("delegate", "fix", "02")])  # a real give-up still is acted on

    def test_continue_blocked_wakes_the_farmer(self):
        i = {"id": "F13:s1:1", "class": "F13", "name": "continue blocked", "action": "judge", "slot": "04",
             "pane": "%4", "session": "s1", "evidence": {}}
        self.assertEqual(kinds(duties.plan_watch({}, ctx(), [i])), [("wake", "judge", "04")])

if __name__ == "__main__":
    unittest.main()
