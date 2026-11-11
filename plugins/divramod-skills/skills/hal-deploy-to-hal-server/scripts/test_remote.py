import json
import unittest
from pathlib import Path

import remote
import testkit

KEY, KNOWN = Path("/nonexistent/key"), Path("/nonexistent/known_hosts")


def status(verdict, **extra):
    return json.dumps({"schema": 1, "site": "accounter", "digest": testkit.DIGEST, "verdict": verdict,
                       "reasons": extra.get("reasons", []), "previous": None})


class RemoteTest(unittest.TestCase):
    def deploy(self, stdout, code, **kw):
        tmp = testkit.scratch()
        ssh = testkit.fake_ssh(tmp, stdout, code)
        out = remote.deploy("accounter", testkit.DIGEST, KEY, KNOWN, True, str(ssh))
        return out, (tmp / "argv").read_text()

    def test_the_forced_command_and_user(self):
        _, argv = self.deploy(status("deployed"), 0)
        self.assertIn(f"hal9k-site-accounter@hal9k.app deploy {testkit.DIGEST}", argv)
        self.assertIn("StrictHostKeyChecking=yes", argv)

    def test_success(self):
        for verdict in ("deployed", "unchanged"):
            out, _ = self.deploy(status(verdict), 0)
            self.assertEqual((out["outcome"], out["ok"], out["exit"], out["tell_user_now"]), ("success", True, 0, False))

    def test_kept_previous(self):
        out, _ = self.deploy(status("kept-previous", reasons=[{"step": "health"}]), 1)
        self.assertEqual((out["outcome"], out["ok"], out["exit"]), ("kept-previous", False, 1))
        self.assertEqual(out["reasons"], [{"step": "health"}])
        self.assertFalse(out["tell_user_now"])

    def test_failed_is_told_at_once(self):
        out, _ = self.deploy(status("failed"), 1)
        self.assertEqual((out["outcome"], out["tell_user_now"], out["exit"]), ("failed", True, 1))
        self.assertIn("candidate is left up", out["meaning"])

    def test_refused_and_unknown_verdict(self):
        self.assertEqual(self.deploy(status("refused"), 1)[0]["outcome"], "refused")
        unknown = self.deploy(status("brand-new"), 1)[0]
        self.assertEqual((unknown["outcome"], unknown["tell_user_now"]), ("unknown", True))

    def test_exit_3_is_pending_not_failed(self):
        out, _ = self.deploy("", 3)
        self.assertEqual((out["outcome"], out["exit"], out["ok"]), ("pending", 3, False))
        self.assertIn("goes on", out["meaning"])

    def test_ssh_failure(self):
        out, _ = self.deploy("", 255)
        self.assertEqual(out["outcome"], "ssh-error")

    def test_no_go_runs_nothing(self):
        tmp = testkit.scratch()
        ssh = testkit.fake_ssh(tmp, status("deployed"), 0)
        with self.assertRaises(PermissionError):
            remote.deploy("accounter", testkit.DIGEST, KEY, KNOWN, False, str(ssh))
        self.assertFalse((tmp / "argv").exists())

    def test_only_a_full_digest_and_a_plain_site(self):
        for digest in ("sha256:abc", "latest", testkit.DIGEST + "\n", "sha256:" + "A" * 64):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                remote.deploy("accounter", digest, KEY, KNOWN, True, "/bin/false")
        with self.assertRaises(ValueError):
            remote.status("Bad Site", KEY, KNOWN, "/bin/false")

    def test_status_command(self):
        tmp = testkit.scratch()
        out = remote.status("accounter", KEY, KNOWN, str(testkit.fake_ssh(tmp, status("deployed"), 0)))
        self.assertTrue(out["ok"])
        self.assertTrue((tmp / "argv").read_text().strip().endswith("hal9k.app status"))


if __name__ == "__main__":
    unittest.main()
