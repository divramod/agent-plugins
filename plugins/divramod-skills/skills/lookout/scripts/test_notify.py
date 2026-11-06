"""Tests of notify.py: every backend faked, no real notification, no real Telegram message, no secret read.
Run from the scripts folder: python3 -m unittest test_notify"""
import json
import unittest
from unittest import mock

import notify

REAL_RECORD = notify.record_notification  # before setUp patches it


class FakeReply:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class NotifyTest(unittest.TestCase):
    def setUp(self):
        # `send` records its notification through hal2-cli-ring: never the real one in a test.
        patch = mock.patch.object(notify, "record_notification", return_value=(False, None))
        self.recorder = patch.start()
        self.addCleanup(patch.stop)

    def test_backends_for(self):
        settings = {"notify": ["desktop", "telegram"]}
        self.assertEqual(notify.backends_for({}, settings), ["desktop", "telegram"])
        self.assertEqual(notify.backends_for({"notify": "default"}, settings), ["desktop", "telegram"])
        self.assertEqual(notify.backends_for({"notify": "none"}, settings), [])
        self.assertEqual(notify.backends_for({"notify": "telegram, desktop"}, settings), ["telegram", "desktop"])
        self.assertEqual(notify.backends_for({}, {}), ["desktop"])

    def test_send_calls_each_backend_once_and_cuts_the_body(self):
        seen = []
        impls = {"a": lambda t, b, f, w: seen.append(("a", t, b, f, w)), "b": lambda t, b, f, w: seen.append(("b",))}
        out = notify.send("T", "x" * 500, "farm", "w1", ["a", "b"], settings={}, impls=impls)
        self.assertEqual(out, [{"backend": "a", "ok": True, "error": None}, {"backend": "b", "ok": True, "error": None}])
        self.assertEqual(len(seen[0][2]), 200)
        self.assertEqual(seen[0][3:], ("farm", "w1"))

    def test_failing_and_unknown_backends_never_raise(self):
        def bad(t, b, f, w):
            raise RuntimeError("down")
        out = notify.send("T", "b", "f", "w", ["bad", "ok", "nope"], settings={},
                          impls={"bad": bad, "ok": lambda *a: None})
        self.assertEqual([(r["backend"], r["ok"]) for r in out], [("bad", False), ("ok", True), ("nope", False)])
        self.assertEqual(out[0]["error"], "down")
        self.assertIn("unknown", out[2]["error"])

    def test_desktop_commands_per_system(self):
        have = lambda *names: (lambda tool: f"/bin/{tool}" if tool in names else None)
        self.assertEqual(notify.desktop_command("T", "B", "darwin", have("terminal-notifier", "osascript"))[0],
                         "terminal-notifier")
        mac = notify.desktop_command('T"x', 'B\\"', "darwin", have("osascript"))
        self.assertEqual(mac[:2], ["osascript", "-e"])
        self.assertEqual(mac[2], 'display notification "B\\\\\\"" with title "T\\"x"')
        self.assertEqual(notify.desktop_command("T", "B", "linux", have("notify-send"))[0], "notify-send")
        self.assertIsNone(notify.desktop_command("T", "B", "linux", have()))
        win = notify.desktop_command("T'", "<B>", "win32", have("powershell"))
        self.assertIn("'T'''", win[-1])
        self.assertIn("&lt;B&gt;", win[-1])

    def test_desktop_backend_uses_the_runner(self):
        calls = []
        runner = lambda argv: (calls.append(argv) or (0, ""))
        notify._desktop("T", "B", "f", "w", runner=runner, system="linux", which=lambda t: "/bin/" + t)
        self.assertEqual(calls, [["notify-send", "--app-name=lookout", "T", "B"]])
        with self.assertRaises(RuntimeError):
            notify._desktop("T", "B", "f", "w", runner=lambda argv: (1, "no bus"), system="linux",
                            which=lambda t: "/bin/" + t)
        with self.assertRaises(RuntimeError):
            notify._desktop("T", "B", "f", "w", runner=runner, system="linux", which=lambda t: None)

    def test_telegram_from_secret_names_posts_json_and_hides_the_token(self):
        reads, posted = [], []
        def secrets(name, repo):
            reads.append((name, repo))
            return {"TOKEN_SEC": "123:SECRETVALUE", "CHAT_SEC": "42"}[name]
        def urlopen(request, timeout):
            posted.append((request.full_url, json.loads(request.data)))
            return FakeReply()
        settings = {"telegram": {"token": "TOKEN_SEC", "chat": "CHAT_SEC", "repo": "/r"}}
        notify._telegram("T", "B", "f", "w", settings=settings, secrets=secrets, urlopen=urlopen)
        self.assertEqual(reads, [("TOKEN_SEC", "/r"), ("CHAT_SEC", "/r")])
        self.assertEqual(posted[0][0], "https://api.telegram.org/bot123:SECRETVALUE/sendMessage")
        self.assertEqual(posted[0][1]["chat_id"], "42")
        self.assertEqual(posted[0][1]["text"], "T\nB")

        def failing(request, timeout):
            raise OSError("cannot reach https://api.telegram.org/bot123:SECRETVALUE/sendMessage")
        with self.assertRaises(RuntimeError) as ctx:
            notify._telegram("T", "B", "f", "w", settings=settings, secrets=secrets, urlopen=failing)
        self.assertNotIn("SECRETVALUE", str(ctx.exception))

    def test_telegram_from_env_and_unconfigured(self):
        posted = []
        env = {"LOOKOUT_TELEGRAM_TOKEN": "t", "LOOKOUT_TELEGRAM_CHAT": "c"}
        self.assertEqual(notify.telegram_credentials({}, env), ("t", "c"))
        self.assertEqual(notify.telegram_credentials({}, {}), ("", ""))
        with self.assertRaises(RuntimeError):
            notify._telegram("T", "B", "f", "w", settings={}, env={}, urlopen=lambda *a, **k: posted.append(1))
        self.assertEqual(posted, [])

    def test_telegram_http_error_status(self):
        env = {"LOOKOUT_TELEGRAM_TOKEN": "t", "LOOKOUT_TELEGRAM_CHAT": "c"}
        with self.assertRaises(RuntimeError):
            notify._telegram("T", "B", "f", "w", settings={}, env=env, urlopen=lambda r, timeout: FakeReply(500))

    def test_read_secret_never_runs_a_shell(self):
        class Done:
            returncode, stdout = 0, b"value\n"
        seen = []
        def fake(argv, **kw):
            seen.append(argv)
            return Done()
        self.assertEqual(notify.read_secret("NAME_SEC", "/repo", fake), "value")
        self.assertEqual(seen, [["hal2-cli-secrets", "show", "NAME_SEC", "--repo", "/repo"]])

    def test_send_records_one_notification_with_the_text_and_the_results(self):
        impls = {"desktop": lambda t, b, f, w: None, "telegram": lambda t, b, f, w: 1 / 0}
        out = notify.send("Watch w", "found it", "hal2", "w1", ["desktop", "telegram"], settings={}, impls=impls)
        self.recorder.assert_called_once_with("hal2", "Watch w: found it", out)
        self.assertEqual([r["ok"] for r in out], [True, False])

    def test_the_record_argv_has_a_channel_per_known_backend(self):
        results = [{"backend": "desktop", "ok": True, "error": None},
                   {"backend": "telegram", "ok": False, "error": "x"}, {"backend": "other", "ok": True, "error": None}]
        self.assertEqual(notify.record_argv("/b/ring", "hal2", results, "T: b"), [
            "/b/ring", "notifications", "add", "--from", "lookout", "--role", "lookout", "--farm", "hal2",
            "--case", "lookout", "--channel", "desktop:sent", "--channel", "telegram:failed", "--", "T: b"])

    def test_record_notification_runs_the_cli_and_never_raises(self):
        ok = [{"backend": "desktop", "ok": True, "error": None}]
        calls = []

        def good(argv):
            calls.append(argv)
            return 0, ""
        self.assertEqual(REAL_RECORD("hal2", "T", ok, which=lambda _: "/b/ring", runner=good), (True, None))
        self.assertEqual(calls[0][:3], ["/b/ring", "notifications", "add"])
        recorded, error = REAL_RECORD("hal2", "T", ok, which=lambda _: "/b/ring", runner=lambda argv: (2, "bad"))
        self.assertFalse(recorded)
        self.assertIn("exit 2: bad", error)
        recorded, error = REAL_RECORD("hal2", "T", ok, which=lambda _: None, runner=good)
        self.assertEqual((recorded, "not installed" in error), (False, True))
        boom = mock.Mock(side_effect=OSError("gone"))
        self.assertIn("OSError", REAL_RECORD("hal2", "T", ok, which=lambda _: "/b/ring", runner=boom)[1])

    def test_nothing_is_recorded_without_a_known_backend(self):
        calls = []
        other = [{"backend": "other", "ok": True, "error": None}]
        self.assertEqual(REAL_RECORD("hal2", "T", other, which=lambda _: "/b/ring", runner=calls.append),
                         (False, None))
        self.assertEqual(REAL_RECORD("hal2", "T", [], which=lambda _: "/b/ring", runner=calls.append), (False, None))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()