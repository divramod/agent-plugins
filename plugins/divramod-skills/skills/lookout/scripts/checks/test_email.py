"""Tests of checks/email.py with a fake `hal2-cli-email` (a script writing JSON), run from the scripts folder:
python3 checks/test_email.py"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(HERE, "email.py")

FAKE = """#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.log"), "a") as f:
    f.write(json.dumps(args) + "\\n")
if os.environ.get("FAKE_FAIL") and args[0] == os.environ.get("FAKE_FAIL_VERB", "sync"):
    sys.stderr.write(os.environ["FAKE_FAIL"]); sys.exit(1)
if args[0] == "sync":
    print("[]")
else:
    print(open(os.path.join(d, "mails.json")).read())
"""


def mail(mid, subject="Hi", sender="hr@acme.de", name="Acme"):
    return {"account": "gmx", "folder": "INBOX", "message_id": mid, "thread_id": "t", "date": "2026-10-14T08:00:00Z",
            "direction": "in", "from": sender, "from_name": name, "to": ["me@x.de"], "cc": [], "subject": subject,
            "snippet": "hello", "attachments": [], "ref": f"email:message/{mid}"}


class EmailCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.state = os.path.join(self.dir, "state")
        os.makedirs(self.state)
        self.fake = os.path.join(self.dir, "fake-email")
        with open(self.fake, "w") as fh:
            fh.write(FAKE)
        os.chmod(self.fake, os.stat(self.fake).st_mode | stat.S_IEXEC)
        self.mails([])

    def tearDown(self):
        self.tmp.cleanup()

    def mails(self, items):
        with open(os.path.join(self.dir, "mails.json"), "w") as fh:
            json.dump(items, fh)

    def calls(self):
        with open(os.path.join(self.dir, "calls.log")) as fh:
            return [json.loads(line) for line in fh]

    def run_check(self, *args, cli=None, **extra):
        env = {"PATH": os.environ["PATH"], "FAKE_DIR": self.dir, "LOOKOUT_STATE": self.state,
               "LOOKOUT_EMAIL_CLI": cli or self.fake, **extra}
        return subprocess.run([sys.executable, CHECK, *args], capture_output=True, text=True, env=env)

    def test_quiet_exits_0(self):
        done = self.run_check("--query", "x")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_new_mail_exits_10_with_contract_lines(self):
        self.mails([mail("a@x", "Einladung"), mail("b@x", "Absage")])
        done = self.run_check("--query", "Bewerbung")
        self.assertEqual(done.returncode, 10, done.stderr)
        lines = [json.loads(line) for line in done.stdout.splitlines()]
        self.assertEqual([item["id"] for item in lines], ["email-a@x", "email-b@x"])
        self.assertEqual(lines[0]["summary"], "Acme <hr@acme.de>: Einladung")
        self.assertEqual(lines[0]["data"]["message_id"], "a@x")
        search = [c for c in self.calls() if c[0] == "messages"][0]
        self.assertIn("--json", search)
        self.assertEqual(search[search.index("--query") + 1], "Bewerbung")
        self.assertIn("--since", search)

    def test_since_state_is_kept_and_reused(self):
        self.run_check()
        path = os.path.join(self.state, "email-since.json")
        with open(path) as fh:
            saved = json.load(fh)["since"]
        self.run_check()
        searches = [c for c in self.calls() if c[0] == "messages"]
        self.assertEqual(searches[1][searches[1].index("--since") + 1], saved)

    def test_dry_run_does_not_write_state(self):
        self.run_check(LOOKOUT_DRY_RUN="1")
        self.assertFalse(os.path.exists(os.path.join(self.state, "email-since.json")))

    def test_lookout_since_used_first_time(self):
        self.run_check(LOOKOUT_SINCE="2026-10-13T10:00:00+00:00")
        search = [c for c in self.calls() if c[0] == "messages"][0]
        self.assertEqual(search[search.index("--since") + 1], "2026-10-13T10:00:00Z")

    def test_known_from_drops_ids(self):
        self.mails([mail("a@x"), mail("b@x")])
        done = self.run_check("--known-from", "echo a@x")
        self.assertEqual(done.returncode, 10)
        self.assertEqual([json.loads(line)["id"] for line in done.stdout.splitlines()], ["email-b@x"])
        done = self.run_check("--known-from", "printf 'a@x\\nb@x\\n'")
        self.assertEqual(done.returncode, 0)

    def test_no_sync(self):
        self.run_check("--no-sync")
        self.assertEqual([c[0] for c in self.calls()], ["messages"])

    def test_missing_cli_exits_75(self):
        done = self.run_check(cli=os.path.join(self.dir, "nope"))
        self.assertEqual(done.returncode, 75)
        self.assertEqual(json.loads(done.stdout)["cause"], "missing")

    def test_not_logged_in_exits_75_auth(self):
        done = self.run_check(FAKE_FAIL="authentication failed: wrong password")
        self.assertEqual(done.returncode, 75)
        self.assertEqual(json.loads(done.stdout)["cause"], "auth")

    def test_offline_exits_75(self):
        done = self.run_check(FAKE_FAIL="connection refused")
        self.assertEqual(done.returncode, 75)
        self.assertEqual(json.loads(done.stdout)["cause"], "offline")

    def test_other_failure_is_broken(self):
        done = self.run_check(FAKE_FAIL="database is corrupt", FAKE_FAIL_VERB="messages")
        self.assertNotIn(done.returncode, (0, 10, 75))
        self.assertIn("corrupt", done.stderr)

    def test_bad_json_is_broken(self):
        with open(os.path.join(self.dir, "mails.json"), "w") as fh:
            fh.write("not json")
        done = self.run_check()
        self.assertNotIn(done.returncode, (0, 10, 75))


if __name__ == "__main__":
    unittest.main()
