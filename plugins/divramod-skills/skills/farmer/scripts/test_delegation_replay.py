"""Hal2 plan 0618 step 3: the stale ledger of 2026-11-05 replayed (38 running, limit 5, most landed), and the
`delegation.py reconcile` command that migrates such a ledger by the tick's own code. Every IO seam is mocked."""

import contextlib
import datetime as dt
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import delegation
import delegation_cli
import delegation_round
import mtm_scan
import tick
from test_delegation import MAIN, Ledger

START = dt.datetime(2026, 10, 3, 10, 0, tzinfo=dt.timezone.utc)
NOW = START + dt.timedelta(days=3)
SCRIPTS = Path(delegation.__file__).resolve().parent


class Stale(Ledger):
    """The farmer's ledger as it stood: running entries whose plans landed long ago, whose fields are removed or reused."""

    def setUp(self):
        super().setUp()
        self.grep, self.slots, self.agents, self.n = "", {}, [], 0
        base = delegation.call

        def call(argv, cwd):
            if argv[:2] == ["git", "grep"]:
                self.calls.append(argv)
                return 0, self.grep
            return base(argv, cwd)
        p = mock.patch.object(delegation, "call", call)
        p.start()
        self.addCleanup(p.stop)

    def field(self, slot, plan="", ahead=0, session=True):
        """Field `slot` in the tick's slot_state, holding `plan` (its plan.md created on the entry's day)."""
        d = Path(tempfile.mkdtemp())
        if plan:
            (d / "plans" / plan).mkdir(parents=True)
            (d / "plans" / plan / "plan.md").write_text("---\nstatus: open\ncreated: 2026-10-03\n---\n")
        self.slots[slot] = {"plan": plan, "ahead": ahead, "path": str(d)}
        if session:
            self.agents.append({"checkout": str(d), "state": "idle", "pane_id": f"%{slot}"})

    def run_entry(self, key, slot, **more):
        delegation.note(MAIN, {"key": key, "state": "running", "slot": slot, **more}, START)

    def states(self):
        return {k: e["state"] for k, e in delegation.ledger(MAIN).items()}

    def log(self):
        return [json.loads(x) for x in (self.tmp / "hal2" / "log.jsonl").read_text().splitlines()]

    def count(self, state):
        return sum(s == state for s in self.states().values())

    def replay(self):
        """38 running entries: 20 landed (10 with their plan recorded, 10 legacy), 5 left an empty field, 3 on removed
        fields, 3 on fields reused for another plan, 1 transplanted, 6 still on an open plan (3 with a session, 2 paused,
        1 without one); one waiting brief."""
        done = []
        for i in range(20):
            slot, plan = f"{i:02d}", f"05{i:02d}-landed"
            self.field(slot, plan, ahead=2)
            self.run_entry(f"landed:{i}", slot, **({"plan": plan} if i < 10 else {}))
            done.append(f"origin/main:plans/{plan}/plan.md:status: done")
        for i in range(5):
            self.field(f"{20 + i}")
            self.run_entry(f"empty:{i}", f"{20 + i}")
        for i in range(3):
            self.run_entry(f"gone:{i}", f"{25 + i}")  # no field 25-27 any more
        for i in range(3):
            self.field(f"{28 + i}", f"06{i:02d}-newer", ahead=1)
            self.run_entry(f"moved:{i}", f"{28 + i}", plan=f"05{i:02d}-older")
        self.field("91", "0700-moved", ahead=1)
        self.run_entry("transplanted", "90", plan="0700-moved")
        self.transplants = [{"id": "t1", "state": "driven", "from": "90", "to": "91", "driven": "2026-10-04T12:00:00Z"}]
        for i, kind in enumerate(("live", "live", "live", "paused", "paused", "sessionless")):
            slot = f"{40 + i}"
            self.field(slot, f"07{i:02d}-open", ahead=3, session=kind != "sessionless")
            self.run_entry(f"working:{kind}:{i}", slot, plan=f"07{i:02d}-open")
            if kind == "paused":
                self.paused[slot] = {"by": "farmer"}
        brief = self.tmp / "waiting.md"
        brief.write_text("brief")
        delegation.note(MAIN, {"key": "brief:next", "state": "waiting", "brief": str(brief), "title": "the next fix"}, START)
        self.sessions, self.grep = self.agents, "\n".join(done) + "\n"
        self.assertEqual(self.count("running"), 38)

    def started(self):
        """The mocked start: a new foreman with a session in field 99 (the tick's field list shows it), nothing real."""
        def start(prompt, main, dry, values=None):
            self.field("99", "0800-new", ahead=1)
            return {"slot": "99", "how": "new"}
        return mock.patch.object(delegation, "start", side_effect=start)


class Replay(Stale):
    def test_the_count_drops_under_the_limit_the_stale_entries_close_once_and_the_waiting_brief_starts(self):
        self.replay()
        self.assertFalse(delegation.has_room(5, delegation_round.capacity(MAIN, self.slots, 5)),
                         "before: the stale entries fill the limit")
        with self.started() as start:
            done = delegation.follow_up(MAIN, self.slots, 5, False, NOW)
        self.assertEqual([d["state"] for d in done].count("landed"), 25)
        self.assertEqual([d["state"] for d in done].count("gone"), 3)
        self.assertEqual([d["state"] for d in done].count("moved"), 3)
        self.assertEqual(self.states()["brief:next"], "running")
        start.assert_called_once()
        self.assertEqual({k: s for k, s in self.states().items() if k.startswith(("gone", "moved"))},
                         {**{f"gone:{i}": "gone" for i in range(3)}, **{f"moved:{i}": "moved" for i in range(3)}})
        t = delegation.ledger(MAIN)["transplanted"]
        self.assertEqual((t["state"], t["slot"], t["from"]), ("running", "91", "90"))
        working = delegation_round.capacity(MAIN, self.slots, 5)
        self.assertEqual(working, 5, "the transplant, the 3 with a session and the new foreman")
        self.assertEqual(self.count("running"), 1 + 6 + 1)
        stops = [c for c in self.calls if c[:len(delegation.STOP)] == delegation.STOP]
        self.assertEqual(len(stops), 25, "only the landed ones' idle sessions stop; gone and moved stop nothing")

    def test_a_second_round_writes_and_logs_nothing_new(self):
        self.replay()
        with self.started():
            delegation.follow_up(MAIN, self.slots, 5, False, NOW)
            delegation.follow_up(MAIN, self.slots, 5, False, NOW + dt.timedelta(minutes=5))  # records field 99's plan
        lines, log = delegation.lines(MAIN), self.log()
        kinds = [e["kind"] for e in log]
        self.assertEqual((kinds.count("landed"), kinds.count("gone"), kinds.count("moved"), kinds.count("transplant")),
                         (25, 3, 3, 1))
        with self.started() as start:
            self.assertEqual(delegation.follow_up(MAIN, self.slots, 5, False, NOW + dt.timedelta(hours=1)), [])
        start.assert_not_called()
        self.assertEqual((delegation.lines(MAIN), self.log()), (lines, log))

    def test_paused_and_sessionless_fields_free_the_room(self):
        self.replay()
        delegation.follow_up(MAIN, self.slots, 5, True, NOW)  # a dry round: nothing written
        self.assertEqual(self.count("running"), 38)
        with self.started():
            delegation.follow_up(MAIN, self.slots, 5, False, NOW)
        running = [e for e in delegation.ledger(MAIN).values() if e["state"] == "running"]
        self.assertEqual(len(running), 8)
        self.assertEqual(delegation_round.capacity(MAIN, self.slots, 5), 5)
        self.paused.clear()
        self.assertEqual(delegation_round.capacity(MAIN, self.slots, 5), 7, "the paused two work again when resumed")


class Command(Stale):
    def test_a_dry_run_lists_every_verdict_with_the_counts_and_writes_nothing(self):
        self.replay()
        before = delegation.lines(MAIN)
        with self.started() as start:
            report = delegation_cli.reconcile(MAIN, self.slots, True, NOW, 5)
        start.assert_not_called()
        self.assertEqual(delegation.lines(MAIN), before)
        self.assertEqual([r["state"] for r in report["entries"]].count("landed"), 25)
        self.assertEqual((report["before"], report["after"]), ({"running": 38, "working": 35},
                                                               {"running": 7, "working": 4}))
        self.assertEqual((report["waiting"], report["room"], report["dry_run"]), (1, 1, True))
        moved = [r for r in report["entries"] if r["to"]]
        self.assertEqual([(r["key"], r["slot"], r["to"]) for r in moved], [("transplanted", "90", "91")])
        self.assertTrue(all(r["reason"] for r in report["entries"]))
        text = delegation_cli.text(report)
        self.assertIn("dry run", text)
        self.assertIn("running 38 -> 7; working 35 -> 4; waiting 1, room for 1 more", text)
        self.assertIn("moved:0  field 28  running -> moved", text)
        self.assertIn("working:paused:3  field 43  running -> running  [not working]", text)

    def test_the_real_run_applies_what_the_dry_run_listed_and_starts_no_brief(self):
        self.replay()
        with self.started() as start:
            report = delegation_cli.reconcile(MAIN, self.slots, False, NOW, 5)
        start.assert_not_called()
        self.assertEqual(self.states()["brief:next"], "waiting", "the tick starts waiting briefs, not the migration")
        self.assertEqual((self.count("landed"), self.count("gone"), self.count("moved"), self.count("running")),
                         (25, 3, 3, 7))
        again = delegation_cli.reconcile(MAIN, self.slots, False, NOW, 5)
        self.assertEqual([r["state"] for r in again["entries"]], ["running"] * 7)
        self.assertEqual(again["before"]["running"], again["after"]["running"])

    def test_main_prints_json_for_the_repo_it_is_given(self):
        self.replay()
        out = io.StringIO()
        argv = ["reconcile", "--repo", MAIN, "--dry-run", "--json", "--limit", "5"]
        with mock.patch.object(mtm_scan, "main_checkout", lambda repo: repo), \
                mock.patch.object(tick, "slot_state", lambda main: self.slots), contextlib.redirect_stdout(out):
            self.assertEqual(delegation_cli.main(argv), 0)
        report = json.loads(out.getvalue())
        self.assertEqual((report["dry_run"], report["before"]["running"], report["room"]), (True, 38, 1))
        self.assertEqual(len(report["entries"]), 38)

    def test_delegation_py_is_the_command(self):
        run = subprocess.run([sys.executable, str(SCRIPTS / "delegation.py"), "reconcile", "--help"],
                             capture_output=True, text=True, cwd=SCRIPTS)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("--dry-run", run.stdout)


if __name__ == "__main__":
    unittest.main()
