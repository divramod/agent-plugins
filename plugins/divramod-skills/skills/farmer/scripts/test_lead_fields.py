"""The lead duty's field classes (hal2 plan 0514 step 4, D8, D16): fields 09, 23 and 29 of 2026-10-30 replayed from
`testdata/lead-0930/fields.json` through `lead_scan.scan` and the dry tick's lead planner (`duties.plan_lead`) are
`pushing` and recorded, never nudged; each other class and the jobsearch field beside hal2's field 02."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import duties
import lead_fields
import lead_scan
import tick

FIXTURE = json.loads((Path(__file__).parent / "testdata/lead-0930/fields.json").read_text())
DONE_PLAN = "# Plan\n\n| # | Step | Status |\n|---|---|---|\n| 1 | a | done |\n| 2 | b | done |\n"
OPEN_PLAN = DONE_PLAN.replace("| 2 | b | done |", "| 2 | b | next |")

def setUpModule():
    """No test of the scan asks the real `hal2-cli-git worktree paused` (plan 0695 D46: the scan reads the marks)."""
    patch = mock.patch.object(lead_scan.field_pause, "load", return_value={})
    patch.start()
    unittest.addModuleCleanup(patch.stop)



class Farm:
    """Scratch fields under `<tmp>/worktree/<repo>/<NN>` (no git: nothing reads as ahead of main, never `landed`)."""

    def __init__(self, base: Path):
        self.base = base

    def field(self, repo: str, slot: str, plan: str, text: str = DONE_PLAN, state=None, why=None) -> Path:
        root = self.base / "worktree" / repo / slot
        (root / "plans" / plan).mkdir(parents=True, exist_ok=True)
        (root / "plans" / plan / "plan.md").write_text(text)
        (root / "plans" / "CURRENT_PLAN").write_text(plan + "\n")
        if state:
            lead_fields.runstate.write(root, plan, state, why)
        return root

    def doc(self, value):
        return json.loads(json.dumps(value).replace("~/.hal/git", str(self.base)))


def agent(root: Path, slot: str, state: str = "idle", minutes: int = 30, **kw) -> dict:
    return {"project": "/x/hal2", "session_id": f"s{root.parent.name}{slot}", "slot": slot, "checkout": str(root),
            "cwd": str(root), "pane_id": f"%{slot}", "state": state, "context_percent": 20,
            "since": int((time.time() - minutes * 60) * 1000), "plan": root.joinpath("plans/CURRENT_PLAN").read_text().strip(),
            **kw}


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.farm = Farm(Path(d.name))
        self.projects = Path(d.name) / "projects"

    def scan(self, agents, queue=None, wq=None):
        queue = self.farm.doc(queue if queue is not None else {"queue": []})
        wq = self.farm.doc(wq if wq is not None else {})
        answers = {"list": agents, "queue": queue, "status": wq}
        with mock.patch.object(lead_scan, "run_json", side_effect=lambda args: answers[args[2] if args[1] == "worktree" else args[1]]), \
                mock.patch.object(lead_scan, "main_checkout", return_value="/x/hal2"), \
                mock.patch.object(lead_scan, "handled", return_value=set()), \
                mock.patch.object(lead_scan.lead_marker, "default_ref", return_value="origin/main"), \
                mock.patch.object(lead_scan, "PROJECTS", self.projects):
            return lead_scan.scan("/x/hal2", False)["needs_help"]


class Replay0930(Base):
    def agents(self):
        out = []
        for slot, f in FIXTURE["fields"].items():
            root = self.farm.field("hal2", slot, f["plan"], state=f["state"], why=f.get("why"))
            a = f["agent"]
            out.append(agent(root, slot, a["state"], a["minutes"], background_tasks=a.get("background_tasks", [])))
        return out

    def test_a_dry_tick_names_09_23_29_pushing_and_nudges_none(self):
        found = self.scan(self.agents(), FIXTURE["queue"], FIXTURE["workqueue"])
        self.assertEqual([(h["slot"], h["kind"]) for h in found], [("09", "pushing"), ("23", "pushing"), ("29", "pushing")])
        for h in found:
            self.assertIn("jobsearch/05 (landing)", h["why"])
        ctx = {"top": "/x/farmer", "main": "/x/hal2", "now": tick.dt.datetime.now(), "log": [], "duties": {"lead"},
               "panes": {}, "agents_by_pane": {}, "landing": set()}
        planned = tick.fresh(duties.plan_lead({}, ctx, {"needs_help": found}), [], ctx["now"])
        self.assertEqual([(a["do"], a["kind"], a["slot"]) for a in planned],
                         [("record", "pushing", s) for s in ("09", "23", "29")])
        self.assertTrue(all("no action" in a["text"] for a in planned))


class Classes(Base):
    def one(self, root, slot="04", queue=None, wq=None, **kw):
        found = self.scan([agent(root, slot, **kw)], queue, wq)
        return (found[0]["kind"], found[0]["why"]) if found else None

    def test_hitched_by_its_ticket_or_its_state(self):
        root = self.farm.field("hal2", "04", "0600-x")
        queue = {"queue": [{"slot": "04", "worktree": str(root), "state": "waiting", "ready": {"head": "c"}}]}
        self.assertEqual(self.one(root, queue=queue)[0], "hitched")
        self.assertEqual(self.one(self.farm.field("hal2", "05", "0601-y", state="hitched"), "05")[0], "hitched")

    def test_done_not_hitched_waiting_blocked_and_landed(self):
        self.assertEqual(self.one(self.farm.field("hal2", "04", "0600-x"))[0], "done-not-hitched")
        waits = self.farm.field("hal2", "06", "0602-z", OPEN_PLAN, "waiting", "the answer to Q3")
        self.assertEqual(self.one(waits, "06"), ("waiting", "waits for the answer to Q3"))
        stuck = self.farm.field("hal2", "07", "0603-w", OPEN_PLAN, "blocked", "no token")
        self.assertEqual(self.one(stuck, "07"), ("blocked-plan", "plan blocked: no token"))
        self.assertEqual(self.one(self.farm.field("hal2", "08", "0604-v", state="landed"), "08")[0], "landed")

    def test_an_open_plan_without_state_stays_idle_in_plan_and_a_busy_one_is_left_alone(self):
        root = self.farm.field("hal2", "04", "0600-x", OPEN_PLAN, "working")
        self.assertEqual(self.one(root)[0], "idle-in-plan")
        shell = [{"id": "b", "type": "subagent", "description": "Plan 0600 row 2"}]
        self.assertIsNone(self.one(root, background_tasks=shell))
        self.assertIsNone(self.one(root, state="working"))

    def test_a_question_wins_over_every_class_but_pushing(self):
        root = self.farm.field("hal2", "04", "0600-x")
        self.assertEqual(self.found(root, "Land it now, or wait for the train?"), "asks")
        hitched = self.farm.field("hal2", "05", "0601-y", state="hitched")
        self.assertEqual(self.found(hitched, "Should I restock after the train?", "05"), "asks")
        pushing = self.farm.field("hal2", "06", "0602-z", state="pushing")
        self.assertEqual(self.found(pushing, "Pushing; hitch after. Let me know?", "06"), "pushing")

    def found(self, root, said, slot="04"):
        with mock.patch.object(lead_scan, "last_assistant_text", return_value=said):
            return self.scan([agent(root, slot)])[0]["kind"]

    def test_jobsearch_02_never_answers_for_hal2_02(self):
        # D16: by path, never the slot number: jobsearch/02 is hitched and pushing, hal2's 02 is neither.
        ours = self.farm.field("hal2", "02", "0600-x", OPEN_PLAN, "working")
        theirs = self.farm.field("jobsearch", "02", "0007-job", state="pushing")
        a = [agent(ours, "02"), dict(agent(theirs, "02"), project="/x/jobsearch")]
        found = self.scan(a, FIXTURE["queue"], FIXTURE["workqueue"])
        self.assertEqual([(h["slot"], h["kind"], h["session"]) for h in found], [("02", "idle-in-plan", a[0]["session_id"])])


if __name__ == "__main__":
    unittest.main()
