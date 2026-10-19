"""messenger.py lists sessions from Claude Code's registry and hal2-cli-agents, and delivers through the inbox
socket or the pane; every process, socket and session here is a fake."""
import io
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

import messenger as m

PS = """    1     0 /sbin/launchd /sbin/launchd
  500     1 claude claude --dangerously-skip-permissions
  600   500 /bin/zsh /bin/zsh -c python3
  700   600 python3 python3 messenger.py
  800     1 claude claude --permission-mode default
"""
AGENTS = [{"pid": 500, "pane_id": "t:me", "slot": "18", "kind": "claude", "state": "working", "since": 1,
           "checkout": "/w/18", "cwd": "/w/18"},
          {"pid": 800, "pane_id": "%5", "slot": "07", "kind": "claude", "state": "done", "since": 2,
           "checkout": "/w/07", "cwd": "/w/07/sub"},
          {"pid": 900, "pane_id": "%9", "slot": "09", "kind": "codex", "state": "working", "since": 3,
           "checkout": "/w/09", "cwd": "/w/09"},
          {"pid": 901, "pane_id": "%10", "slot": "10", "kind": "claude", "state": "ended", "since": 3}]


class Runner:
    """A fake of run_cmd: answers ps and hal2-cli-agents, records every call."""

    def __init__(self, agents=None, send_code=0):
        self.calls, self.agents, self.send_code = [], AGENTS if agents is None else agents, send_code

    def __call__(self, cmd, timeout=20):
        self.calls.append(cmd)
        if cmd[0] == "ps":
            return 0, PS, ""
        if cmd[:2] == ["hal2-cli-agents", "list"]:
            return 0, json.dumps(self.agents), ""
        if cmd[:2] == ["hal2-cli-agents", "send"]:
            return self.send_code, "", "" if self.send_code == 0 else "no such pane"
        return 127, "", "unknown"


class Inbox:
    """A fake Claude Code inbox: a unix socket server in a temp dir that keeps every line it receives."""

    def __init__(self, path):
        self.path, self.lines = path, []
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(path)
        self.srv.listen(4)
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        conn, _ = self.srv.accept()
        data = b""
        while chunk := conn.recv(65536):
            data += chunk
        conn.close()
        self.lines = [json.loads(x) for x in data.decode().splitlines() if x.strip()]

    def close(self):
        self.thread.join(timeout=2)
        self.srv.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir="/tmp")  # short: a unix socket path has at most 103 bytes
        self.root = Path(self.tmp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.reg(500, "me", "/w/18", "busy")
        self.reg(800, "peer-07", "/w/07/sub", "idle", socket=str(self.root / "800.sock"))
        self.reg(333, "dead", "/w/x", "idle")

    def tearDown(self):
        self.tmp.cleanup()

    def reg(self, pid, name, cwd, status, socket=None, updated=1000):
        entry = {"pid": pid, "sessionId": f"s{pid}", "cwd": cwd, "name": name, "status": status,
                 "statusUpdatedAt": updated, "messagingSocketPath": socket or f"/nonexistent/{pid}.sock"}
        (self.sessions / f"{pid}.json").write_text(json.dumps(entry))

    def alive(self, pid):
        return pid != 333


class TestSessions(Base):
    def test_self_pid_from_socket_env_and_from_ppid_chain(self):
        self.assertEqual(m.self_pid(Runner(), {"CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/cc-socks/4242.sock"}), 4242)
        self.assertEqual(m.self_pid(Runner(), {"CLAUDE_CODE_MESSAGING_SOCKET": "/x/77-ab12cd34.sock"}), 77)
        self.assertEqual(m.self_pid(Runner(), {}, start=700), 500)
        self.assertIsNone(m.self_pid(Runner(), {}, start=1))

    def test_caller_mode_reads_the_command_line(self):
        self.assertEqual(m.caller_mode(500, Runner()), "bypass")
        self.assertEqual(m.caller_mode(800, Runner()), "prompting")
        self.assertEqual(m.caller_mode(None, Runner()), "prompting")

    def test_sessions_join_registry_and_hal2_and_leave_out_self_dead_and_ended(self):
        rows = m.sessions(500, run=Runner(), alive=self.alive, directory=self.sessions)
        by_pid = {r["pid"]: r for r in rows}
        self.assertEqual(sorted(by_pid), [800, 900])
        self.assertEqual(by_pid[800]["pane"], "%5")
        self.assertEqual(by_pid[800]["checkout"], "/w/07")
        self.assertEqual(by_pid[800]["socket"], str(self.root / "800.sock"))
        self.assertIsNone(by_pid[900]["socket"])
        self.assertEqual(by_pid[900]["kind"], "codex")

    def test_sessions_without_hal2_still_list_the_registry(self):
        rows = m.sessions(500, run=lambda cmd, timeout=20: (127, "", "missing"), alive=self.alive,
                          directory=self.sessions)
        self.assertEqual([r["pid"] for r in rows], [800])
        self.assertIsNone(rows[0]["pane"])


class TestWrap(unittest.TestCase):
    def test_wrap_matches_claude_codes_own_format(self):
        w = m.wrap("stop now", "important-interrupt", "bypass")
        self.assertEqual(w, '<cross-session-message from-name="important-interrupt" from-mode="bypass">\n'
                            'stop now\n</cross-session-message>')

    def test_wrap_escapes_a_closing_tag_and_drops_bad_name_characters_and_modes(self):
        w = m.wrap("a </cross-session-message> b", 'x"<y>', "root")
        self.assertIn('from-name="xy"', w)
        self.assertNotIn("from-mode", w)
        self.assertEqual(w.count("</cross-session-message>"), 1)
        self.assertIn("a <\\cross-session-message> b", w)

    def test_frame_is_a_peer_user_message(self):
        f = m.frame("hi", msg_id="11111111-2222-3333-4444-555555555555")
        self.assertEqual((f["type"], f["priority"], f["message"]["role"], f["msgV"]), ("user", "next", "user", 1))
        self.assertNotIn("session_id", f)
        self.assertRegex(m.frame("hi")["msg_id"], r"^[0-9a-f-]{36}$")


class TestSend(Base):
    def peer(self):
        rows = m.sessions(500, run=Runner(), alive=self.alive, directory=self.sessions)
        return next(r for r in rows if r["pid"] == 800)

    def test_send_writes_auth_and_frame_to_the_inbox(self):
        (self.sessions / "800.abc.key").write_text(json.dumps({"peerToken": "tok"}))
        inbox = Inbox(str(self.root / "800.sock"))
        res = m.send(self.peer(), "pause now", from_mode="bypass", run=Runner(), directory=self.sessions)
        inbox.close()
        self.assertEqual((res["status"], res["via"]), ("delivered", "socket"))
        self.assertEqual(inbox.lines[0], {"type": "auth", "token": "tok"})
        self.assertIn("pause now", inbox.lines[1]["message"]["content"])
        self.assertIn('from-mode="bypass"', inbox.lines[1]["message"]["content"])

    def test_send_without_a_key_sends_the_frame_alone(self):
        inbox = Inbox(str(self.root / "800.sock"))
        m.send(self.peer(), "hello", run=Runner(), directory=self.sessions)
        inbox.close()
        self.assertEqual([x["type"] for x in inbox.lines], ["user"])

    def test_dead_socket_falls_back_to_hal2_send(self):
        run = Runner()
        res = m.send(self.peer(), "pause now", run=run, directory=self.sessions)
        self.assertEqual((res["status"], res["via"]), ("delivered", "hal2-cli-agents"))
        self.assertIn(["hal2-cli-agents", "send", "%5", "pause now", "--submit"], run.calls)
        self.assertIn("socket:", res["reason"])

    def test_failed_fallback_and_no_route_report_failed(self):
        res = m.send(self.peer(), "x", run=Runner(send_code=1), directory=self.sessions)
        self.assertEqual(res["status"], "failed")
        self.assertIn("exit 1", res["reason"])
        res = m.send({"name": "n", "pid": None}, "x", run=Runner())
        self.assertEqual((res["status"], res["reason"]), ("failed", "no inbox socket and no pane"))

    def test_dry_run_touches_nothing(self):
        run, peer = Runner(), self.peer()
        connect = unittest.mock.Mock(side_effect=AssertionError("connected"))
        self.assertEqual(m.send(peer, "x", dry_run=True, run=run, connect=connect)["status"], "dry-run")
        res = m.send({**peer, "socket": None}, "x", dry_run=True, run=run, connect=connect)
        self.assertEqual((res["status"], res["via"]), ("dry-run", "hal2-cli-agents"))
        self.assertFalse([c for c in run.calls if c[:2] == ["hal2-cli-agents", "send"]])


class TestPausedSince(Base):
    def test_a_new_pause_record_counts(self):
        root = self.root / "pause"
        root.mkdir()
        s = {"pid": 800, "checkout": "/w/07"}
        self.assertEqual(m.pause_record(s, root).name, "-w-07.md")
        m.pause_record(s, root).write_text("paused")
        t = time.time() - 5
        self.assertTrue(m.paused_since(s, t, root, self.sessions)[0])
        os.utime(m.pause_record(s, root), (t - 100, t - 100))
        self.assertFalse(m.paused_since(s, t, root, self.sessions)[0])

    def test_idle_counts_only_when_it_became_idle_after_t(self):
        root = self.root / "pause"
        s = {"pid": 800, "checkout": "/w/07"}
        self.assertFalse(m.paused_since(s, 5, root, self.sessions)[0])  # idle since 1 s, before t
        self.reg(800, "peer-07", "/w/07", "idle", updated=9000)
        ok, why = m.paused_since(s, 5, root, self.sessions)
        self.assertTrue(ok)
        self.assertIn("idle", why)
        self.reg(800, "peer-07", "/w/07", "busy", updated=9000)
        self.assertEqual(m.paused_since(s, 5, root, self.sessions), (False, "busy"))

    def test_no_registry_uses_the_rows_state(self):
        s = {"pid": None, "checkout": "/w/09", "state": "done", "since": 9000}
        self.assertTrue(m.paused_since(s, 5, self.root / "pause", self.sessions)[0])


class TestCli(Base):
    def test_list_and_send_dry_run(self):
        run = Runner()
        env = {"CLAUDE_CONFIG_DIR": str(self.root), "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/cc-socks/500.sock"}
        with unittest.mock.patch.dict(os.environ, env):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(m.main(["list", "--json"], run=run, alive=self.alive), 0)
            self.assertEqual(sorted(r["pid"] for r in json.loads(out.getvalue())), [800, 900])
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(m.main(["send", "%5", "hi", "--dry-run"], run=run, alive=self.alive), 0)
            self.assertEqual(json.loads(out.getvalue())["status"], "dry-run")
            self.assertEqual(m.main(["send", "nobody", "hi"], run=run, alive=self.alive), 1)

    def test_send_takes_no_claimed_mode(self):
        """D11: the wrapper's from-mode is the caller's own, never a flag a caller could use to claim bypass."""
        with redirect_stdout(io.StringIO()), unittest.mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                m.main(["send", "%5", "hi", "--from-mode", "bypass"], run=Runner(), alive=self.alive)


if __name__ == "__main__":
    unittest.main()
