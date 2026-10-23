"""Hal2 plan 0412 step 1 (tollman learning L65): the orphan rule sees every live session of a field.

Replays 2026-10-20: the tollman's boss started `/handoff c` nine times into fields 01, 02, 04 and 11 that held
terminal-host sessions. The rounds that did it read `hal2-cli-agents list --json` under heavy load and got nothing
back (`last-scan.json` 20:30, summaries 15:14 and 20:25: every field's agent none, the rounds around them 10-14), and
an unreadable list read as "no session anywhere". The fixtures are shaped like the real list (`t:<id>` panes under the
session `terminal`, sleeping, idle, failed). No real session, tmux or hal2 CLI is touched: every CLI is a fake."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import live_sessions
import mtm_scan as scan

HOME = "/Users/mod/.hal/git/worktree/hal2"


def host(slot: str, state: str, home: str = HOME, **kw) -> dict:
    """A terminal-host entry as `hal2-cli-agents list --json` prints it (2026-10-20)."""
    path = f"{home}/{slot}"
    return {"pane_id": f"t:tmvfzjq{slot}x", "session": "terminal", "window_index": 0, "window_name": slot,
            "pane_index": 0, "title": "", "kind": "claude", "cwd": path, "checkout": path,
            "project": "/Users/mod/a/hal2", "slot": slot, "plan": None, "lead": None, "role": "foreman",
            "plan_progress": None, "pid": 17162, "state": state, "source": "hook", "since": 1792463259141,
            "context_percent": 30, "context_over": False, "session_id": f"s-{slot}", "autoclear": None,
            "background_tasks": [], "sent": [], **kw}


def tmux(slot: str, state: str, home: str = HOME, **kw) -> dict:
    return {**host(slot, state, home), "pane_id": f"%{slot}", "session": "work", "window_name": slot, **kw}


class Lookup(unittest.TestCase):
    def test_a_terminal_host_session_sleeping_idle_or_failed_is_live_an_ended_one_is_gone(self):
        agents = [host("01", "sleeping"), host("02", "idle"), host("04", "failed"), host("05", "ended")]
        by = live_sessions.by_checkout(agents)
        for slot, state in (("01", "sleeping"), ("02", "idle"), ("04", "failed")):
            self.assertEqual(live_sessions.session_of(by, f"{HOME}/{slot}")["state"], state, slot)
        self.assertIsNone(live_sessions.session_of(by, f"{HOME}/05"), "ended is hal2's gone")
        self.assertIsNone(live_sessions.session_of(by, f"{HOME}/11"))
        self.assertEqual(scan.agents_by_checkout(agents), by, "the scan's name is the same lookup")

    def test_tmux_is_unchanged_and_a_busy_session_wins(self):
        agents = [tmux("03", "done"), host("03", "working"), tmux("03", "idle"), tmux("07", "blocked-question")]
        by = live_sessions.by_checkout(agents)
        self.assertEqual(by[f"{HOME}/03"]["pane_id"], "t:tmvfzjq03x", "the busy one, whatever its host")
        self.assertEqual(by[f"{HOME}/07"]["pane_id"], "%07")

    def test_every_kind_counts_and_a_session_without_a_state_too(self):
        agents = [host("08", "idle", kind="antigravity"), host("09", "sleeping", kind="gemini")]
        agents.append({k: v for k, v in host("10", "x").items() if k != "state"})
        by = live_sessions.by_checkout(agents)
        self.assertEqual({s for s in ("08", "09", "10") if live_sessions.session_of(by, f"{HOME}/{s}")},
                         {"08", "09", "10"})

    def test_a_checkout_is_matched_by_its_realpath(self):
        with tempfile.TemporaryDirectory() as d:
            real = Path(d) / "real"
            (real / "01").mkdir(parents=True)
            os.symlink(real, Path(d) / "link")
            by = live_sessions.by_checkout([host("01", "sleeping", home=str(Path(d) / "link"))])
            self.assertIsNotNone(live_sessions.session_of(by, str(real / "01")))

    def test_an_unreadable_list_is_none_and_never_no_session(self):
        for answer in (None, "", {"error": "timeout"}, {"agents": None}, 3):
            self.assertIsNone(live_sessions.read(lambda args, a=answer: a), answer)
        self.assertEqual(live_sessions.read(lambda args: {"agents": [host("01", "idle")]}), [host("01", "idle")])
        self.assertEqual(live_sessions.read(lambda args: [host("01", "idle")]), [host("01", "idle")])
        self.assertEqual(live_sessions.read(lambda args: {"agents": []}), [])
        self.assertEqual(live_sessions.live_session(None, f"{HOME}/01")["state"], "unknown")
        self.assertIsNone(live_sessions.live_session([host("01", "ended")], f"{HOME}/01"))
        self.assertEqual(live_sessions.live_session([host("01", "failed")], f"{HOME}/01")["state"], "failed")

    def test_the_cli_is_asked_once_and_a_failure_or_timeout_reads_as_none(self):
        done = lambda code, out: mock.Mock(returncode=code, stdout=out)
        with mock.patch.object(live_sessions.subprocess, "run", return_value=done(0, '{"agents": []}')) as run:
            self.assertEqual(live_sessions.read(), [])
        self.assertEqual(run.call_args.args[0], ["hal2-cli-agents", "list", "--json"])
        for effect in (done(1, '{"agents": []}'), done(0, "not json"), done(0, ""),
                       live_sessions.subprocess.TimeoutExpired("x", 1), OSError("missing")):
            kw = {"side_effect": effect} if isinstance(effect, Exception) else {"return_value": effect}
            with mock.patch.object(live_sessions.subprocess, "run", **kw):
                self.assertIsNone(live_sessions.read(), effect)


class Replay(unittest.TestCase):
    """The scan of 2026-10-20 20:30: fields 01, 02, 04 hold terminal-host sessions, 11 holds none."""

    def scan(self, home: str, agents):
        answers = lambda args, cwd=None: agents if args == ["hal2-cli-agents", "list", "--json"] else None
        wts = [{"path": f"{home}/{s}", "branch": s} for s in ("01", "02", "04", "05", "11")]
        with mock.patch.object(scan, "run", return_value=""), mock.patch.object(scan, "run_json", answers), \
                mock.patch.object(scan, "worktrees", return_value=wts), \
                mock.patch.object(scan, "unmerged", return_value=5), \
                mock.patch.object(scan.mtm_ci, "ci_mode", return_value=False), \
                mock.patch.object(scan, "state_dir", return_value=Path(home) / "state"):
            return scan.snapshot(home, 24, fetch=False)

    def fields(self, d: str) -> str:
        for s in ("01", "02", "04", "05", "11"):
            (Path(d) / s).mkdir()
        return d

    def orphans(self, snap: dict) -> list[str]:
        return [f["slot"] for f in snap["findings"] if f["kind"] == "work-without-agent"]

    def test_terminal_host_sessions_sleeping_idle_failed_are_no_orphans(self):
        with tempfile.TemporaryDirectory() as d:
            home = self.fields(d)
            listed = [host("01", "sleeping", home), host("02", "idle", home), host("04", "failed", home),
                      host("05", "ended", home)]
            got = self.scan(home, {"agents": listed})
        self.assertEqual(self.orphans(got), ["05", "11"], "only the fields without a live session")
        self.assertEqual({w["slot"]: w["agent_state"] for w in got["worktrees"]},
                         {"01": "sleeping", "02": "idle", "04": "failed", "05": None, "11": None})
        self.assertTrue(got["agents_read"])

    def test_an_unreadable_list_names_no_orphan_and_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            got = self.scan(self.fields(d), None)
        self.assertEqual(self.orphans(got), [], "fail closed: no field is 'no agent session'")
        self.assertEqual({w["agent_state"] for w in got["worktrees"]}, {"unknown"})
        self.assertFalse(got["agents_read"])
        self.assertIn("hal2-cli-agents list unreadable", scan.render_summary(got, [], [], ""))

    def test_an_unreadable_list_never_lets_a_held_holder_be_released_as_sessionless(self):
        an_hour_ago = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
        held = {"slot": "04", "state": "held", "pid": 0, "enqueued": an_hour_ago, "hold": {"reason": "reserved"}}
        w = {"slot": "04", "ahead": 5, "agent_state": "unknown", "agent_idle_seconds": 0}
        snap = {"now": time.time(), "queue": [scan_ticket(held)], "worktrees": [w], "landings": [], "tests": {},
                "load": {"load1": 1.0, "cores": 10, "per_core": 0.1}, "paused": None}
        self.assertEqual([f["kind"] for f in scan.findings(snap)], [], "no reserved-idle while the agent is unknown")
        w["agent_state"] = None
        self.assertEqual([f["kind"] for f in scan.findings(snap)], ["reserved-idle"], "known to have none: found")

    def test_a_servant_with_a_terminal_host_session_is_no_orphan(self):
        with tempfile.TemporaryDirectory() as d:
            home = self.fields(d)
            for s in ("02", "11"):
                (Path(home) / s / "plans").mkdir()
                (Path(home) / s / "plans" / "LEAD").write_text("07 0412 1\n")
            with mock.patch.object(scan.lead_marker, "missing", return_value=["2 commits not in origin/07"]):
                got = self.scan(home, {"agents": [host("02", "sleeping", home)]})
        self.assertEqual(self.orphans(got), ["01", "04", "05", "11"])
        self.assertEqual([f["lead"]["slot"] for f in got["findings"] if f["slot"] == "11"], ["07"])


def scan_ticket(t: dict) -> dict:
    """A queue ticket as the snapshot shapes it."""
    return {**t, "process_alive": False, "parked": False, "awaiting_slot": False, "active_seconds": 0}


if __name__ == "__main__":
    unittest.main()
