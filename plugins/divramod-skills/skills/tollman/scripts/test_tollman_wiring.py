"""Hal2 plan 0608 step 5 (D8, D9): nothing types `/tollman act` or `/farmer act` any more. The tick's wake and the
handoff's clear-and-continue type the resume command `/continue` (the user, 2026-11-03: "/handoff c, /farmer act and
/tollman act — these should go"), which in a role's session runs the role's act script first (the continue skill's
`act` and `wake` ways); `tollman.py act` and `farmer.py wake` stay as scripts."""
# enforces .adr/deterministic-first.md

import datetime as dt
import re
from unittest import mock

import farmer_frame
import deliver
import roles
import wake
from test_do_first import Frame
from test_farmer import NOW
from test_tollman import WIRING

RESUME = "/continue"
GONE = re.compile(r"""["'](/tollman act|/farmer act)\b""")


class Typed(Frame):
    def setUp(self):
        super().setUp()
        self.sent = []
        for p in (mock.patch.object(deliver, "send", lambda pane, text, *a, **k: self.sent.append((pane, text))),
                  mock.patch.object(deliver, "agent", lambda pane: {"session_id": "s1", "context_percent": 5})):
            p.start()
            self.addCleanup(p.stop)

    def test_both_roles_resume_with_continue(self):
        self.assertEqual((WIRING.act, roles.FARMER.act, wake.ACT), (RESUME, RESUME, RESUME))

    def test_the_tollman_s_wake_types_continue(self):
        r = wake.hand_over(str(self.wm), self.main, {"wake": [self.red_item(51)]}, NOW, WIRING)
        self.assertEqual((r["woken"], self.sent), (True, [("%9", RESUME)]))

    def test_a_timed_out_handoff_clears_and_types_continue(self):
        with mock.patch.object(deliver, "agent", lambda pane: {"session_id": "s1", "context_percent": wake.CLEAR_AT}):
            wake.hand_over(str(self.wm), self.main, {"wake": [self.red_item(51)]}, NOW, WIRING)
        self.assertEqual(self.sent, [("%9", WIRING.handoff)])
        with mock.patch.object(wake, "plain_clear", return_value=None):
            wake.hand_over(str(self.wm), self.main, {}, NOW + wake.HANDOFF_TIMEOUT + dt.timedelta(minutes=1), WIRING)
        self.assertEqual(self.sent[-1], ("%9", RESUME))

    def test_no_role_script_types_the_old_commands(self):
        roots = farmer_frame.SCRIPTS.parents[1]
        found = [f"{p.relative_to(roots)}:{n}" for p in sorted(roots.glob("*/scripts/*.py"))
                 if not p.name.startswith("test_")
                 for n, line in enumerate(p.read_text().splitlines(), 1) if GONE.search(line)]
        self.assertEqual(found, [])
