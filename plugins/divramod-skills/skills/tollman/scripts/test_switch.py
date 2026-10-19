"""Hal2 plan 0375 D4, D19: `tollman.py sleep|wake` are thin calls of hal2-roles' sleep flag (`hal2-cli-roles sleep
tollman on|off --by <who>`, the user by default, plan 0365 D3) and say what came of it; `drop` clears the standing
train through the engine. The CLI is faked: its JSON as hal2-cli-roles gives it, never the installed binary."""

import contextlib
import io
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import switch
import tollman

FIELD = Path("/w/hal2/tollman-hal2")
SLEPT = {"role": "tollman", "asleep": True, "by": "user", "at": "2026-10-18T10:00:00Z", "why": "ci down",
         "file": str(FIELD / "roles/tollman/sleep.json")}


class Verbs(unittest.TestCase):
    def call(self, *argv, code=0, answer=json.dumps(SLEPT)):
        calls, out, err = [], io.StringIO(), io.StringIO()

        def run(args, **kw):
            calls.append(args)
            return subprocess.CompletedProcess(args, code, answer if code == 0 else "", answer if code else "")

        with mock.patch.object(switch.subprocess, "run", run), \
                mock.patch.object(switch.mtm_scan, "main_checkout", lambda r: "/m"), \
                mock.patch.object(switch.roles, "slot_dir", lambda main, role: FIELD), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tollman.main([*argv, "--repo", "/no/such/farm/tollman-hal2"])
        return code, calls, out.getvalue() + err.getvalue()

    def test_sleep_sets_the_flag_by_the_user(self):
        code, calls, text = self.call("sleep", "--why", "ci down")
        self.assertEqual(code, 0)
        self.assertEqual(calls, [["hal2-cli-roles", "sleep", "tollman", "on", "--repo", "hal2", "--worktrees", "/w/hal2",
                                  "--by", "user", "--why", "ci down", "--json"]])
        self.assertIn("the tollman is asleep now", text)

    def test_wake_by_the_farmer_removes_it(self):
        code, calls, text = self.call("wake", "--by", "farmer", "--why", "ignored")
        self.assertEqual((code, calls), (0, [["hal2-cli-roles", "sleep", "tollman", "off", "--repo", "hal2",
                                              "--worktrees", "/w/hal2", "--by", "farmer", "--json"]]))
        self.assertIn("awake now", text)

    def test_a_refused_flag_exits_with_the_cli_text(self):
        code, _, text = self.call("sleep", code=1, answer="hal2-cli-roles: no field /w/hal2/tollman-hal2")
        self.assertEqual((code, text.strip()), (1, "hal2-cli-roles: no field /w/hal2/tollman-hal2"))

    def test_drop_clears_the_train(self):
        with mock.patch.object(engine, "clear", return_value=(0, "train x broken up: the tollman is asleep")) as clear, \
                contextlib.redirect_stdout(io.StringIO()):
            code = tollman.main(["drop", "--why", "the tollman is asleep", "--repo", "/f/tollman-hal2"])
        self.assertEqual(code, 0)
        clear.assert_called_once_with("/f/tollman-hal2", "the tollman is asleep")


if __name__ == "__main__":
    unittest.main()
