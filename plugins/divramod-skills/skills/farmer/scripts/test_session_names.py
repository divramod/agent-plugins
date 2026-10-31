"""L77, L98 of the tollman: a relay names its target's SendMessage name, found by the field's checkout, never by the
field number (hal2's 03 got voice-agent's 03-1a)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import deliver
import mtm_scan
import session_names
import tick


class Names(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.sessions = self.tmp / "claude" / "sessions"
        self.sessions.mkdir(parents=True)
        self.home = self.tmp / "home"
        self.hal2 = self.home / ".hal/git/worktree/hal2/03"
        self.voice = self.home / ".hal/git/worktree/voice-agent/03"
        for p in (self.hal2, self.voice):
            p.mkdir(parents=True)

    def session(self, pid, cwd, name, updated=1):
        (self.sessions / f"{pid}.json").write_text(json.dumps({"pid": pid, "cwd": str(cwd), "name": name,
                                                               "updatedAt": updated}))

    def test_the_field_s_own_live_session_is_named_never_another_farm_s_same_number(self):
        self.session(os.getpid(), self.voice, "03-1a", 9)
        self.assertIsNone(session_names.name_of(self.hal2, self.sessions), "voice-agent's 03 is not hal2's")
        self.session(os.getpid() + 0, self.hal2, "03-7f", 2)  # the same pid file is rewritten: the newer session
        self.assertEqual(session_names.name_of(self.hal2, self.sessions), "03-7f")
        self.session(999999, self.hal2, "03-dead", 5)
        self.assertEqual(session_names.name_of(self.hal2, self.sessions), "03-7f", "a dead pid's file is no session")

    def test_a_refused_send_relays_with_the_target_s_name(self):
        self.session(os.getpid(), self.hal2, "03-7f")
        out = {"wake": [], "notify": []}
        a = tick.act("trains", "car-red", "send", "03", pane="t:x", text="fix it", key="k")
        env = {"CLAUDE_CONFIG_DIR": str(self.tmp / "claude"), "HOME": str(self.home)}
        with mock.patch.dict(os.environ, env), mock.patch.object(Path, "home", return_value=self.home), \
                mock.patch.object(deliver, "send", return_value="agent is working"), \
                mock.patch.object(mtm_scan, "log"), mock.patch("acks.stamp_send"):
            tick.execute(a, "/x/farmer", "/x/hal2", out)
        self.assertEqual([(r["do"], r["to"]) for r in out["relay"]], [("relay", "03-7f")])


if __name__ == "__main__":
    unittest.main()
