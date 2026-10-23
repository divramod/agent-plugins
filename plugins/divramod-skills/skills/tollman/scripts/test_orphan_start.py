"""Hal2 plan 0412 step 2: the orphan rule's start guard. Fakes only: no real agents list, no real session started."""

import datetime as dt
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import farmer_frame
import boss
import mtm_scan
import orphan_start

NOW = dt.datetime(2026, 10, 20, 20, 30)
MAIN = "/x/hal2"


def entry(slot, state, pane="t:abc123", **kw):
    """An `hal2-cli-agents list --json` entry shaped like the real ones: a terminal host's `t:<id>` pane."""
    return {"kind": "claude", "pane_id": pane, "session": "terminal" if pane.startswith("t:") else "main",
            "state": state, "checkout": f"/x/wt/{slot}", **kw}


class Guard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(mtm_scan, "DATA", self.tmp)
        p.start()
        self.addCleanup(p.stop)
        self.started = []

    def run_start(self, listing, slot="01"):
        """The round carries out the action the boss planned for an orphan 01: (exit code, stdout, log entries)."""
        a = self.planned(slot)
        argv = a["argv"][2:]  # past the python and the script
        out = io.StringIO()

        def fake_run(start, **kw):
            self.started.append(start)
            return SimpleNamespace(returncode=0, stdout="started\n", stderr="")

        with redirect_stdout(out):
            code = orphan_start.main(argv, read=lambda: listing, run=fake_run)
        log = mtm_scan.entries(mtm_scan.state_dir(MAIN, "tollman") / "log.jsonl")
        return code, out.getvalue(), log

    def planned(self, slot):
        w = {"slot": slot, "path": f"/x/wt/{slot}", "ahead": 1, "plan": "0085-x", "agent_state": None, "pane": None}
        f = {"kind": "work-without-agent", "slot": slot, "why": ""}
        with mock.patch.object(boss, "has_handoff", return_value=True):
            acts = boss.plan({"findings": [f], "queue": [], "worktrees": [w], "landings": [], "priority": None},
                             {"now": NOW, "log": [], "main": MAIN})
        return [a for a in acts if a["kind"] == "orphan"][0]

    def test_the_orphan_start_is_the_guard_around_the_same_start(self):
        a = self.planned("01")
        self.assertEqual(a["do"], "run")
        self.assertTrue(a["argv"][1].endswith("orphan_start.py"))
        self.assertEqual(a["argv"][a["argv"].index("--") + 1:],
                         ["hal2-cli-git", "worktree", "run", "01", "--agent", "claude", "--detach", "--prompt",
                          "/handoff c"])
        self.assertEqual(a["argv"][a["argv"].index("--path") + 1], "/x/wt/01")

    def test_a_field_with_no_session_still_gets_its_start(self):
        code, out, log = self.run_start([entry("02", "idle")])
        self.assertEqual((code, out), (0, "started\n"))
        self.assertEqual(self.started[0][:4], ["hal2-cli-git", "worktree", "run", "01"])
        self.assertEqual(log, [])

    def test_a_session_that_appears_between_scan_and_start_stops_the_start(self):
        # The race: the scan (and the plan) saw no agent in 01; by the start a terminal host holds the field.
        for state in ("sleeping", "idle", "failed", "working", "starting", "done"):
            self.started.clear()
            code, out, log = self.run_start([entry("01", state)])
            self.assertEqual(code, orphan_start.SKIPPED, state)
            self.assertEqual(self.started, [], f"no second session into a {state} one")
            self.assertIn("holds a live session", out)
            self.assertIn(state, out)
            self.assertEqual(log[-1]["kind"], "orphan-skipped")
            self.assertEqual(log[-1]["slot"], "01")

    def test_a_tmux_session_stops_it_too_an_ended_one_does_not(self):
        code, _, _ = self.run_start([entry("01", "idle", pane="%7")])
        self.assertEqual((code, self.started), (orphan_start.SKIPPED, []))
        code, _, _ = self.run_start([entry("01", "ended")])
        self.assertEqual((code, len(self.started)), (0, 1))

    def test_an_unreadable_list_fails_closed(self):
        code, out, log = self.run_start(None)
        self.assertEqual((code, self.started), (orphan_start.SKIPPED, []))
        self.assertIn("could not be read", out)
        self.assertEqual(log[-1]["kind"], "orphan-skipped")

    def test_a_log_that_cannot_be_written_still_skips(self):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(mtm_scan, "log", side_effect=FileNotFoundError("x")):
            code = orphan_start.main(self.planned("01")["argv"][2:], read=lambda: [entry("01", "idle")],
                                     run=lambda *a, **k: self.fail("started"))
        self.assertEqual(code, orphan_start.SKIPPED)

    def test_the_starts_exit_code_is_the_scripts(self):
        a = self.planned("01")
        done = SimpleNamespace(returncode=1, stdout="", stderr="no field")
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            code = orphan_start.main(a["argv"][2:], read=lambda: [], run=lambda *x, **k: done)
        self.assertEqual((code, err.getvalue()), (1, "no field"))


if __name__ == "__main__":
    unittest.main()
