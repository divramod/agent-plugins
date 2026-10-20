import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import quiet
import stopall


class QuietTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["STOP_ALL_AGENT_WORK_ROOT"] = self.tmp.name

    def tearDown(self):
        del os.environ["STOP_ALL_AGENT_WORK_ROOT"]
        self.tmp.cleanup()

    def test_under(self):
        self.assertTrue(quiet.under("/w/hal2/07", ["/w/hal2/07/"]))
        self.assertTrue(quiet.under("/w/hal2/07/code", ["/w/hal2/07"]))
        self.assertFalse(quiet.under("/w/hal2/070", ["/w/hal2/07"]))

    def test_actions_have_undo_where_reversible(self):
        self.assertEqual(quiet.action({"kind": "session", "pid": 5, "session": "/w"})[1], ("CONT", 5))
        self.assertIsNone(quiet.action({"kind": "orphan", "pid": 5})[1])
        self.assertEqual(quiet.action({"kind": "ollama", "pids": [1, 2]})[1], ["open", "-a", "Ollama"])
        agent = quiet.action({"kind": "agent", "label": "x.y", "plist": "/p/x.y.plist", "what": "LaunchAgent x.y"})
        self.assertEqual(agent[0][:2], ["launchctl", "bootout"])
        self.assertEqual(agent[1][-1], "/p/x.y.plist")
        self.assertIsNone(quiet.action({"kind": "report"}))

    def test_restore_undoes_in_reverse(self):
        stopall.add_actions([{"text": "a", "do": ["true"], "undo": ["echo", "a"]},
                             {"text": "b", "do": ["true"], "undo": None},
                             {"text": "c", "do": ["STOP", 9], "undo": ["CONT", 9]}])
        done = []
        with mock.patch.object(quiet, "perform", side_effect=lambda s: done.append(s) or True):
            quiet.restore(False)
        self.assertEqual(done, [("CONT", 9), ["echo", "a"]])

    def test_important_work_is_recognized(self):
        self.assertEqual(quiet.important("rsync -a ~/b/media /Volumes/USB/"), "copies or moves data")
        self.assertEqual(quiet.important("mv /Users/mod/models /Volumes/USB/models"), "copies or moves data")
        self.assertEqual(quiet.important("git push origin main"), "git write or landing")
        self.assertEqual(quiet.important("bash utils/deploy/hal9k/deploy.sh"), "deploys")
        self.assertEqual(quiet.important("brew upgrade"), "installs software")
        self.assertEqual(quiet.important("rustc --crate-name time"), "")
        self.assertEqual(quiet.important("cargo build --release"), "")

    def test_apply_waits_for_confirmation(self):
        rows = [{"kind": "session", "pid": 11, "session": "/w", "what": "rsync -a x /Volumes/U/", "confirm": "copies"},
                {"kind": "session", "pid": 12, "session": "/w", "what": "cargo build"}]
        done = []
        with mock.patch.object(quiet, "scan", return_value=rows), \
                mock.patch.object(quiet, "perform", side_effect=lambda s: done.append(s) or True):
            self.assertEqual(quiet.apply([], False, False, []), 3)
            self.assertEqual(done, [("STOP", 12)])
            done.clear()
            self.assertEqual(quiet.apply([], False, False, ["11"]), 0)
            self.assertIn(("STOP", 11), done)

    def test_frozen_runner_is_restarted_by_the_undo(self):
        table = {1: {"pid": 1, "ppid": 0, "cmd": "launchd"},
                 20: {"pid": 20, "ppid": 1, "cmd": "/Users/m/actions-runner-a/bin/Runner.Listener run"},
                 21: {"pid": 21, "ppid": 20, "cmd": "/x/Runner.Worker spawnclient"},
                 22: {"pid": 22, "ppid": 21, "cmd": "cargo build"}}
        self.assertTrue(quiet.runner_related(table, 22))
        self.assertFalse(quiet.runner_related(table, 1))
        rows = [{"kind": "session", "pid": 22, "session": "/w", "what": "cargo build"}]
        sig, calls = [], []
        with mock.patch.object(quiet, "scan", return_value=rows), mock.patch.object(quiet, "procs", return_value=table), \
                mock.patch.object(quiet, "runner_services", return_value=[("actions.runner.o-r.mac-host-a", "/p")]), \
                mock.patch.object(quiet, "perform", side_effect=lambda s: sig.append(s) or True):
            quiet.apply([], False, False, [])
        texts = [a["text"] for a in stopall.actions()]
        self.assertEqual(texts[0], "restart runner service actions.runner.o-r.mac-host-a")
        self.assertTrue(texts[1].startswith("freeze 22"))
        with mock.patch.object(quiet, "perform", side_effect=lambda s: calls.append(s) or True):
            quiet.restore(False)
        # SIGCONT first, then the service is kickstarted
        self.assertEqual(calls[0], ("CONT", 22))
        self.assertEqual(calls[1][:3], ["launchctl", "kickstart", "-k"])
        self.assertTrue(calls[1][3].endswith("/actions.runner.o-r.mac-host-a"))

    def test_no_runner_restart_for_an_unrelated_freeze(self):
        table = {1: {"pid": 1, "ppid": 0, "cmd": "launchd"}, 30: {"pid": 30, "ppid": 1, "cmd": "cargo build"}}
        rows = [{"kind": "session", "pid": 30, "session": "/w", "what": "cargo build"}]
        with mock.patch.object(quiet, "scan", return_value=rows), mock.patch.object(quiet, "procs", return_value=table), \
                mock.patch.object(quiet, "runner_services", return_value=[("actions.runner.x", "/p")]), \
                mock.patch.object(quiet, "perform", return_value=True):
            quiet.apply([], False, False, [])
        self.assertEqual([a["text"] for a in stopall.actions()], ["freeze 30 (/w)"])

    def test_ollama_never_through_its_cli(self):
        # `ollama ps` starts Ollama.app when the server is down: only HTTP may ask it.
        src = Path(quiet.__file__).read_text()
        self.assertNotIn('["ollama"', src)


if __name__ == "__main__":
    unittest.main()
