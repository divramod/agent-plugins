"""The boss's wakes the tollman closed by hand again and again (plan 0490 step 11): L43, L78, L94 replayed."""

import datetime as dt
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401
import boss
import boss_quiet
import mtm_scan
import tick

NOW = dt.datetime(2026, 10, 24, 18, 20)


def wt(slot, **kw):
    return {"slot": slot, "path": f"/x/{slot}", "ahead": 1, "plan": "", "agent_state": None, "pane": f"%{slot}", **kw}


def snap(findings, worktrees=(), landings=()):
    return {"findings": list(findings), "queue": [], "worktrees": list(worktrees), "landings": list(landings),
            "priority": None}


class Quiet(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(mtm_scan, "DATA", self.tmp)
        p.start()
        self.addCleanup(p.stop)
        self.main = str(self.tmp / "hal2")

    def plan(self, s, log=()):
        planned = boss.plan(s, {"now": NOW, "log": list(log), "main": self.main})
        return [(a["do"], a["kind"], a["slot"]) for a in tick.fresh(planned, list(log), NOW)], planned

    def test_l78_a_skip_listed_orphan_is_never_woken_and_the_cli_keeps_the_list(self):
        f = {"kind": "work-without-agent", "slot": "45", "why": "3 commits not on main, plan -, no agent session"}
        s = snap([f], [wt("45", path="/nowhere")])
        self.assertEqual(self.plan(s)[0], [("wake", "orphan", "45")])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(boss_quiet.main(["skip", "add", "45", "--why", "parked by the user", "--repo",
                                              self.main]), 0)
        self.assertEqual(self.plan(s)[0], [], "skip-listed: no wake in any round")
        self.assertEqual(boss_quiet.skipped(self.main, "tollman")["45"]["why"], "parked by the user")
        with redirect_stdout(io.StringIO()):
            boss_quiet.main(["skip", "rm", "45", "--repo", self.main])
        self.assertEqual(self.plan(s)[0], [("wake", "orphan", "45")])

    def test_l94_a_closed_flaky_wake_stays_closed_until_the_test_fails_in_a_new_field(self):
        f = {"kind": "flaky-candidate", "slot": "08,13", "why": "alfred_peek failed 2x", "test": "alfred_peek"}
        got, planned = self.plan(snap([f]))
        self.assertEqual(got, [("wake", "flaky", "08,13")])
        log = [{"at": NOW.isoformat(), "key": planned[0]["key"]}]
        later = NOW + dt.timedelta(hours=5)
        again = boss.plan(snap([dict(f, slot="13,08")]), {"now": later, "log": log, "main": self.main})
        self.assertEqual(tick.fresh(again, log, later), [], "the same fields: closed, also hours later")
        new = boss.plan(snap([dict(f, slot="08,13,21")]), {"now": later, "log": log, "main": self.main})
        self.assertEqual([a["kind"] for a in tick.fresh(new, log, later)], ["flaky"], "a new field wakes")

    def test_l43_a_research_plan_with_a_manual_landing_is_a_record_never_a_wake(self):
        field = self.tmp / "02"
        (field / "plans" / "0400-research-x").mkdir(parents=True)
        (field / "plans" / "0400-research-x" / "plan.md").write_text("---\nlanding: manual\n---\n# x\n")
        f = {"kind": "work-not-queued", "slot": "02", "why": "4 commits not on main, plan 0400-research-x, agent idle"}
        got, _ = self.plan(snap([f], [wt("02", path=str(field), plan="0400-research-x")]))
        self.assertEqual(got, [("record", "research-waits", "02")])
        (field / "plans" / "0400-research-x" / "plan.md").write_text("---\nlanding: auto\n---\n")
        got, _ = self.plan(snap([f], [wt("02", path=str(field), plan="0400-research-x")]))
        self.assertEqual(got, [("wake", "work-not-queued", "02")], "a research plan landing by itself")
        plain = dict(f, why="4 commits not on main, plan 0401-x, agent idle")
        got, _ = self.plan(snap([plain], [wt("02", path=str(field), plan="0401-x")]))
        self.assertEqual(got, [("wake", "work-not-queued", "02")])


if __name__ == "__main__":
    unittest.main()
