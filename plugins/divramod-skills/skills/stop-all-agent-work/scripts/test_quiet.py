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

    def test_ollama_never_through_its_cli(self):
        # `ollama ps` starts Ollama.app when the server is down: only HTTP may ask it.
        src = Path(quiet.__file__).read_text()
        self.assertNotIn('["ollama"', src)


if __name__ == "__main__":
    unittest.main()
