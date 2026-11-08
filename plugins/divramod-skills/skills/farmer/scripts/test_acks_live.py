"""Hal2 plan 0731 step 8: acks_live.py on a fake CLI in a scratch root (no tmux, no real session, no real log)."""

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

import acks_live


class Fake:
    """hal2-cli-git, hal2-cli-agents, git and acks.py as one scripted world: a started field gets a row that rests
    after `rest_after` lists, `instruct` logs an ask and (unless `silent`) the session acks it."""

    def __init__(self, lv, silent=(), refuse_remove=(), dialog=None, paused=(), starting=()):
        self.paused, self.starting = set(paused), set(starting)
        self.starting_host, self.alive, self.kills = {}, set(), []
        self.lv, self.silent, self.refuse_remove, self.dialog = lv, set(silent), set(refuse_remove), dialog
        self.fields, self.rows, self.calls, self.n = {"35", "90"}, {}, [], 0

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        if argv[:3] == ["git", "-C", self.lv.main] and argv[3] == "worktree":
            return 0, "".join(f"worktree /w/{f}\nbranch refs/heads/{f}\n\n" for f in sorted(self.fields)), ""
        if argv[:3] == ["git", "-C", self.lv.main] and argv[3] == "branch":
            return 0, "", ""
        if argv[:3] == ["hal2-cli-git", "worktree", "paused"]:
            return 0, json.dumps({"schema": 1, "fields": [{"field": f} for f in sorted(self.paused)]}), ""
        if argv[:3] == ["hal2-cli-git", "worktree", "new"]:
            self.fields.add(argv[3])
            return 0, "", ""
        if argv[:3] == ["hal2-cli-git", "worktree", "run"]:
            nn, kind = argv[3], argv[5]
            self.n += 1
            self.fields.add(nn)
            self.rows[nn] = {"slot": nn, "kind": kind, "project": self.lv.main, "pane_id": f"t:h{self.n}",
                             "state": "starting", "lists": 0}
            if kind in self.starting:
                pid = 1000 + self.n
                self.starting_host[nn] = pid
                self.alive.add(pid)
                (self.lv.terminals / f"h{self.n}.json").write_text(json.dumps({"id": f"h{self.n}", "host_pid": pid}))
            return 0, json.dumps({"mode": "detached", "pane": f"t:h{self.n}", "slot": nn}), ""
        if argv[:3] == ["hal2-cli-git", "worktree", "remove"]:
            nn = argv[3]
            if nn in self.refuse_remove:
                return 4, "", "a live agent session refused the stop"
            if nn in self.starting_host and self.starting_host[nn] in self.alive:
                return 4, json.dumps({"status": "refused", "reason": "busy: the agent is starting"}), ""
            self.fields.discard(nn)
            self.rows.pop(nn, None)
            return 0, "", ""
        if argv[:3] == ["hal2-cli-agents", "list", "--json"]:
            for r in self.rows.values():
                r["lists"] += 1
                if r["kind"] == "codex" and self.dialog == "codex":
                    r["state"] = "idle"  # codex lists idle under its update dialog
                elif r["lists"] >= 2 and not (self.dialog and r["kind"] == self.dialog) \
                        and r["kind"] not in self.starting:
                    r["state"] = "idle"
            return 0, json.dumps({"agents": list(self.rows.values())}), ""
        if argv[:2] == ["hal2-cli-agents", "capture"]:
            if self.dialog == "codex":
                return 0, "  1. Update now (runs `npm install -g @openai/codex`)\n  2. Skip", ""
            return 0, "Do you trust the contents of this project?\n> Yes" if self.dialog else "> ", ""
        if argv[:2] == ["hal2-cli-agents", "send"]:
            if argv[3:] == ["Enter", "--key"]:
                self.dialog = None
            if argv[3:] == ["2", "--key"] and self.dialog == "codex":
                self.keys_codex = True
            return 0, "", ""
        if argv[0] == sys.executable and argv[2] == "instruct":
            nn, text = argv[3], argv[4]
            ack_id = f"{nn}-{1 + self.lv.log.read_text().count('ask-ack') if self.lv.log.exists() else 1}"
            kind = self.rows[nn]["kind"]
            pane = self.rows[nn]["pane_id"]
            (self.lv.sent / f"{pane[2:]}.jsonl").write_text(
                json.dumps({"ts": 1, "text": f"farmer [{ack_id}]: {text}", "confirmed": kind != "antigravity"}) + "\n")
            with self.lv.log.open("a") as f:
                f.write(json.dumps({"at": "2026-11-08T10:00:00", "kind": "ask-ack", "id": ack_id, "slot": nn}) + "\n")
                if kind not in self.silent:
                    f.write(json.dumps({"at": "2026-11-08T10:00:05", "kind": "ack", "id": ack_id, "what": "done",
                                        "slot": nn}) + "\n")
            return 0, json.dumps({"id": ack_id, "text": text}), f"acks.py: {ack_id} sent to {pane}"
        return 127, "", f"unexpected {argv}"


class Clock:
    def __init__(self):
        self.t = 0.0

    def sleep(self, s):
        self.t += s

    def now(self):
        return dt.datetime(2026, 11, 8, 10, 0) + dt.timedelta(seconds=self.t)


class LiveCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "sent").mkdir()
        (self.tmp / "terminals").mkdir()
        self.record = self.tmp / "terminals" / "host35.json"
        self.record.write_text('{"id": "host35", "kind": "claude"}')
        self.clock = Clock()
        self.lv = acks_live.Live(repo=str(self.tmp / "35"), main=str(self.tmp / "main"), log=self.tmp / "log.jsonl",
                                 sent=self.tmp / "sent", terminals=self.tmp / "terminals",
                                 env={"HAL2_TERMINAL": "host35", "PATH": "/bin"},
                                 sleep=self.clock.sleep, clock=lambda: self.clock.t, now=self.clock.now)
        self.log_out = self.tmp / "live.md"

    def go(self, kinds, **kw):
        self.fake = Fake(self.lv, **kw)
        self.lv.run = self.fake
        self.lv.kill = self.kill
        code = acks_live.run_all(self.lv, kinds, self.log_out)
        return code, self.log_out.read_text()

    def test_every_kind_acks_one_field_at_a_time_and_every_field_is_removed(self):
        code, md = self.go(["grok", "codex", "claude"])
        self.assertEqual(code, 0)
        self.assertIn("| grok | 91 | 91-1 | y ", md)  # 90 is taken
        self.assertIn("| codex | 91 | 91-2 | y ", md)  # 91 was freed again: one session at a time
        self.assertIn("| y | y |", md)  # verified, removed
        self.assertEqual(self.fake.fields, {"35", "90"})
        self.assertIn("unchanged", md)
        starts = [c for c in self.fake.calls if c[:3] == ["hal2-cli-git", "worktree", "run"]]
        self.assertEqual([c[3:] for c in starts][0], ["91", "--agent", "grok", "--fresh", "--detach", "--json"])
        removes = [c for c in self.fake.calls if c[:3] == ["hal2-cli-git", "worktree", "remove"]]
        self.assertTrue(all("--force" not in c and "--stop" in c and "--remote" in c for c in removes))

    def test_claude_is_asked_for_the_shell_ack(self):
        self.go(["claude"])
        text = next(c[4] for c in self.fake.calls if c[0] == sys.executable)
        self.assertIn("acks.py ack <the id in brackets above> done", text)
        grok = Fake(self.lv)
        self.lv.run = grok
        acks_live.run_all(self.lv, ["grok"], self.log_out)
        self.assertNotIn("SendMessage", next(c[4] for c in grok.calls if c[0] == sys.executable))

    def test_a_paused_field_is_never_started(self):
        code, md = self.go(["grok"], paused={"91", "92"})
        self.assertEqual(code, 0)
        self.assertIn("| grok | 93 | 93-1 | y ", md)
        self.assertFalse(any(c[3:4] in (["91"], ["92"]) for c in self.fake.calls if c[0] == "hal2-cli-git"))

    def test_a_non_claude_listed_starting_is_sent_once_it_settles_a_claude_never(self):
        code, md = self.go(["grok", "claude"], starting={"grok", "claude"})
        self.assertIn("| grok | 91 | 91-1 | y ", md)
        self.assertIn("never rested", md)  # claude listed starting: never sent
        self.assertEqual(code, 1)

    def kill(self, pid, sig):
        self.fake.kills.append((pid, sig))
        alive = pid in self.fake.alive
        if sig:
            self.fake.alive.discard(pid)
        return alive

    def test_a_stop_refused_for_a_starting_agent_ends_the_runs_own_host_then_removes(self):
        _, md = self.go(["grok"], starting={"grok"})
        self.assertIn("y (own host ended first: --stop refused a busy agent)", md)
        self.assertEqual(self.fake.kills[0], (1001, 15))
        self.assertEqual(self.fake.fields, {"35", "90"})
        self.assertFalse(any("--force" in c for c in self.fake.calls))

    def test_no_ack_is_bounded_and_fails_the_run(self):
        code, md = self.go(["grok", "codex"], silent={"codex"})
        self.assertEqual(code, 1)
        self.assertIn(f"no ack in {acks_live.ACK_WAIT}s", md)
        self.assertLessEqual(self.clock.t, acks_live.START_WAIT * 2 + acks_live.ACK_WAIT + 4 * acks_live.POLL)

    def test_a_trust_dialog_is_answered_and_an_unverified_send_is_shown(self):
        code, md = self.go(["antigravity"], dialog="antigravity")
        self.assertIn(["hal2-cli-agents", "send", "t:h1", "Enter", "--key"], self.fake.calls)
        self.assertIn("| antigravity | 91 | 91-1 | y ", md)
        self.assertIn("| n | y |", md)  # verified n, removed y
        self.assertEqual(code, 0)  # antigravity is tried, not required

    def test_codexs_update_dialog_is_skipped_before_the_send(self):
        code, md = self.go(["codex"], dialog="codex")
        self.assertEqual(code, 0)
        sends = [c[3] for c in self.fake.calls if c[:2] == ["hal2-cli-agents", "send"]]
        self.assertEqual(sends, ["2", "Enter"])
        self.assertIn("| codex | 91 | 91-1 | y ", md)

    def test_a_refused_removal_is_reported_never_forced(self):
        _, md = self.go(["grok"], refuse_remove={"91"})
        self.assertIn("refused (4): a live agent session refused the stop", md)
        self.assertFalse(any("--force" in c for c in self.fake.calls))

    def test_a_changed_host_record_fails_the_run(self):
        orig = acks_live.check

        def rewrite(lv, kind):
            self.record.write_text('{"id": "host35", "kind": "grok"}')
            return orig(lv, kind)
        acks_live.check = rewrite
        try:
            code, md = self.go(["grok"])
        finally:
            acks_live.check = orig
        self.assertEqual(code, 1)
        self.assertIn("CHANGED", md)

    def test_bin_goes_first_on_path_for_the_subprocesses_only(self):
        env = {"PATH": "/usr/bin"}
        self.assertEqual(acks_live.with_bin(env, str(self.tmp))["PATH"], f"{self.tmp.resolve()}:/usr/bin")
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertEqual(acks_live.with_bin(env, "")["PATH"], "/usr/bin")


if __name__ == "__main__":
    unittest.main()
