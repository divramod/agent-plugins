"""The overview table (hal2 plan 0591 step 2): fixture facts give exact rows and lines; the sources read a tmp git repo
with fields and LEAD markers through faked tools, and every missing tool gives `-`, never an error."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import overview
import overview_sources
import state_sources
import servant_testkit as kit  # on sys.path since state_sources

MAIN = "/w/hal2"
FIELD = lambda wt: f"/w/.hal/hal2/{wt}"  # noqa: E731


def agent(state="working", **kw) -> dict:
    return {"kind": "claude", "state": state, "pid": 100, **kw}


def fixture() -> dict:
    pp = {"slug": "0591-s-overview-table", "number": 591, "title": "s overview table with a much too long name",
          "done": 1, "total": 4}
    return {
        "repo": "hal2", "main": MAIN, "agents_known": True,
        "agents": {
            MAIN: agent("idle", effort="high"),
            FIELD("farmer-hal2"): agent("done", pid=7),
            FIELD("64"): agent(plan_progress=pp, effort="medium",
                               background_tasks=[{"type": "subagent"}, {"type": "shell"}, {"type": "subagent"}]),
            FIELD("05"): agent("idle", pid=55, plan_progress={**pp, "number": 575, "title": "sccache", "done": 12,
                                                              "slug": "0575-x", "total": 12}),
            FIELD("31"): agent("idle", pid=31),
        },
        "fields": [{"wt": w, "path": FIELD(w), "lead": lead} for w, lead in
                   (("64", None), ("05", None), ("31", "64"), ("32", "64"), ("farmer-hal2", None),
                    ("tollman-hal2", None))],
        "queue": [{"slot": "05", "position": 0, "holding": True, "ready": {"at": "x"}},
                  {"worktree": FIELD("64"), "position": 2, "holding": False, "ready": None}],
        "asks": ["05"], "questions": {"64": ["Q1", "Q3"], "05": []}, "argv_effort": {"7": "xhigh"},
        "timer": "enabled",
    }


class New(unittest.TestCase):
    """The `new` column (plan 0543 D102): signed done and total deltas against the previous run."""

    def new(self, last, done=1, total=4):
        f = fixture()
        f["agents"][FIELD("64")]["plan_progress"].update(done=done, total=total)
        return {x["wt"]: x["new"] for x in overview.rows(f, last)}["64"]

    def test_plus_minus_none_and_a_new_field(self):
        last = {"done": {"64:591": 1}, "total": {"64:591": 4}}
        self.assertEqual(self.new(last, 3, 9), "+2/+5")
        self.assertEqual(self.new(last, 0, 1), "-1/-3")
        self.assertEqual(self.new(last, 1, 4), "-/-")
        self.assertEqual(self.new({}, 3, 9), "-/-")

    def test_a_field_that_appears_counts_all_its_steps_and_one_that_leaves_is_gone(self):
        self.assertEqual(self.new({"done": {"05:575": 1}, "total": {"05:575": 1}}), "+1/+4")
        self.assertEqual(self.new({"done": {"05:575": 1}, "total": {"05:575": 1}}, 0, 6), "-/+6")
        before = overview.snapshot(fixture())
        f = fixture()
        del f["agents"][FIELD("05")]
        after = overview.snapshot(f)
        self.assertEqual(sum(before["done"].values()) - sum(after["done"].values()), 12)
        self.assertEqual(sum(before["total"].values()) - sum(after["total"].values()), 12)

    def test_a_servants_row_and_a_field_without_steps_are_dashes(self):
        r = {x["wt"]: x["new"] for x in overview.rows(fixture(), {"done": {"31:None": 0}, "total": {"31:None": 0}})}
        self.assertEqual((r["31"], r["05"]), ("-", "+12/+12"))

    def test_snapshot_and_atomic_save_round_trip(self):
        snap = overview.snapshot(fixture())
        self.assertEqual(snap["done"], {"05:575": 12, "64:591": 1})
        self.assertEqual(snap["total"], {"05:575": 12, "64:591": 4})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "last.json"
            self.assertEqual(overview.load_last(path), {})
            overview.save_last(path, snap)
            self.assertEqual(overview.load_last(path), snap)
            self.assertEqual([p.name for p in path.parent.iterdir()], ["last.json"])
            path.write_text("{bad")
            self.assertEqual(overview.load_last(path), {})

    def test_the_state_file_lives_in_the_state_dir(self):
        with mock.patch.dict("os.environ", {"XDG_STATE_HOME": "/s"}):
            self.assertEqual(str(overview.last_path("my repo")), "/s/hal2/get-state/overview-last-my-repo.json")


class Rows(unittest.TestCase):
    def test_roles_on_top_then_fields_by_name(self):
        r = overview.rows(fixture())
        self.assertEqual([x["wt"] for x in r], ["steward", "tollman", "farmer", "05", "31", "64"])
        self.assertEqual(r[0], {**{k: "-" for k, _ in overview.COLUMNS}, "wt": "steward", "status": "online (idle)",
                                "effort": "high"})
        self.assertEqual((r[1]["status"], r[1]["effort"]), ("offline, timer enabled", "-"))
        self.assertEqual((r[2]["status"], r[2]["effort"]), ("online (done)", "xhigh"))

    def test_a_field_row(self):
        r = {x["wt"]: x for x in overview.rows(fixture())}
        self.assertEqual(r["64"], {"wt": "64", "plan": "0591", "name": "s overview table with a much", "steps": "1/4", "new": "-/-",
                                   "open_q": "2", "decision": "yes", "status": "working", "servants": "2",
                                   "hands": "2", "effort": "medium", "queue": "3"})
        self.assertEqual({k: r["05"][k] for k in ("open_q", "decision", "status", "queue", "effort")},
                         {"open_q": "0", "decision": "yes", "status": "idle (plan done)", "queue": "1 hitched holds",
                          "effort": "-"})
        self.assertEqual({k: r["31"][k] for k in ("plan", "name", "steps", "open_q", "decision", "queue")},
                         dict.fromkeys(("plan", "name", "steps", "open_q", "decision", "queue"), "-"))

    def test_unknown_facts_are_dashes(self):
        f = {**fixture(), "agents_known": False, "agents": {}, "queue": None, "timer": None, "argv_effort": {}}
        r = overview.rows(f)
        self.assertEqual([x["status"] for x in r], ["-", "-, timer -", "-"])

    def test_rendered_lines(self):
        lines = overview.render(overview.rows(fixture()))
        self.assertEqual(lines[0], "| wt      | plan | name                         | steps | new | open q | decision? | "
                                   "status                 | servants | hands | effort | queue           |")
        self.assertTrue(lines[1].startswith("|---------|------|"))
        self.assertEqual(lines[-1], "| 64      | 0591 | s overview table with a much | 1/4   | -/- | 2      | yes       | "
                                    "working                | 2        | 2     | medium | 3               |")
        self.assertEqual(len({len(x) for x in lines}), 1)

    def test_json_has_a_schema(self):
        p = overview.payload(fixture())
        self.assertEqual((p["schema"], p["repo"], p["columns"][5]), (1, "hal2", "open_q"))
        json.dumps(p)


def fake_tool(answers: dict):
    def tool(args, cwd=None, timeout=None):
        return answers.get(args[0])
    return tool


class Sources(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kit.install(self)  # a fake hal2-cli-plans: a LEAD is read through `servant show --json` (plan 0594)
        root = Path(tmp.name).resolve()
        self.main = root / "farm"
        self.main.mkdir()
        def git(*a):
            subprocess.run(["git", *a], cwd=self.main, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
        for wt in ("64", "31", "tollman-farm"):
            git("worktree", "add", "-q", "-b", wt, str(root / "fields" / wt))
        (root / "fields/31/plans").mkdir()
        (root / "fields/31/plans/LEAD").write_text("64 0591 2\n")
        self.f64 = str(root / "fields/64")
        plan = root / "fields/64/plans/0591-s-overview-table"
        plan.mkdir(parents=True)
        (plan / "questions.md").write_text("## Q1 · 2026-11-03 · agent · open\n\n"
                                           "## Q2 · 2026-11-03 · agent · answered\n")
        self.agents = [
            {"kind": "claude", "state": "working", "pid": 4242, "checkout": self.f64,
             "plan_progress": {"slug": "0591-s-overview-table"}},
            {"kind": "codex", "state": "idle", "pid": 9, "checkout": str(root / "fields/31")},
            {"kind": "claude", "state": "idle", "pid": 8, "checkout": str(root / "elsewhere")},
        ]

    def facts(self, answers: dict) -> dict:
        with mock.patch.object(state_sources, "tool", fake_tool(answers)), \
             mock.patch.object(state_sources, "farmer_log", lambda main: [{"kind": "ask", "slot": "64"}]), \
             mock.patch.object(overview_sources.sys, "platform", "darwin"):
            return overview_sources.facts(str(self.main))

    def test_facts_from_the_tools(self):
        queue = {"queue": [{"slot": "64", "repo": "farm", "position": 1, "ready": {"at": "x"}},
                           {"slot": "02", "repo": "other", "position": 0}]}
        f = self.facts({"hal2-cli-agents": json.dumps({"agents": self.agents}), "hal2-cli-git": json.dumps(queue),
                        "ps": "4242 claude --model opus --effort low\n", "launchctl": "-\t0\tlocal.tollman.farm\n"})
        self.assertEqual((f["repo"], f["main"], f["timer"]), ("farm", str(self.main), "enabled"))
        self.assertEqual(sorted((x["wt"], x["lead"]) for x in f["fields"]),
                         [("31", "64"), ("64", None), ("tollman-farm", None)])
        self.assertEqual(list(f["agents"]), [self.f64])
        self.assertEqual((f["argv_effort"], f["questions"]), ({"4242": "low"}, {"64": ["Q1"]}))
        self.assertEqual([t["slot"] for t in f["queue"]], ["64"])
        r = {x["wt"]: x for x in overview.rows(f)}
        self.assertEqual((r["64"]["effort"], r["64"]["open_q"], r["64"]["decision"], r["64"]["servants"],
                          r["64"]["queue"]), ("low", "1", "yes", "1", "2 hitched"))

    def test_missing_tools_give_dashes(self):
        f = self.facts({})
        self.assertEqual((f["agents_known"], f["queue"], f["timer"], f["argv_effort"]), (False, None, None, {}))
        lines = overview.render(overview.rows(f))
        self.assertEqual(len(lines), 5)
        self.assertIn("| tollman | -    | -    | -     | -   | -      | -         | -, timer - |", lines[3])

    def test_timer_off_macos_is_unknown(self):
        with mock.patch.object(overview_sources.sys, "platform", "linux"):
            self.assertIsNone(overview_sources.timer("hal2"))


if __name__ == "__main__":
    sys.exit(unittest.main())
