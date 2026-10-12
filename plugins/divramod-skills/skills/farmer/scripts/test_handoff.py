import datetime as dt
import io
import json
import os
from contextlib import redirect_stdout
from unittest import mock

import farmer
import handoff
import wake
from test_farmer import NOW, Repo


class Handoff(Repo):
    """`farmer.py handoff`: handoff.md's path and sections; --clear only once it is written for this handoff."""

    def setUp(self):
        super().setUp()
        self.main, self.calls = str(self.main), []

        def cli(*args, timeout=30):
            if args[0] == "list":
                return 0, json.dumps([{"pane_id": "%9", "checkout": str(self.slot), "session_id": "s1"}])
            self.calls.append(args)
            return self.answer

        self.answer = (0, '{"status": "started", "pane": "%9"}')
        p = mock.patch.object(wake.deliver, "cli", cli)
        p.start()
        self.addCleanup(p.stop)

    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = farmer.main(["handoff", *argv, "--repo", str(self.slot)])
        return code, out.getvalue()

    def write(self, at: dt.datetime):
        f = handoff.path(self.main)
        f.write_text("# farmer handoff\n")
        os.utime(f, (at.timestamp(), at.timestamp()))

    def test_the_owner_handoff_is_renamed_and_a_missing_one_shows_its_sections(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("missing", out)
        self.assertIn("## Open threads", out)
        old = handoff.mtm_scan.state_dir(self.main) / "owner-handoff.md"
        old.write_text("old")
        self.assertEqual(handoff.path(self.main).read_text(), "old")
        self.assertFalse(old.exists())
        self.assertNotIn("missing", self.run_cli()[1])

    def test_clear_refuses_without_a_fresh_handoff(self):
        code, out = self.run_cli("--clear")
        self.assertEqual((code, self.calls), (1, []))
        self.assertIn("missing", out)
        self.write(dt.datetime.now() - dt.timedelta(minutes=30))
        code, out = self.run_cli("--clear")
        self.assertEqual((code, self.calls), (1, []))
        self.assertIn("older", out)

    def test_a_handoff_older_than_the_pending_request_is_not_fresh(self):
        self.write(NOW - dt.timedelta(minutes=1))
        wake.write(self.main, {"woken_at": None, "items": [{"seq": 1}],
                               "handoff": {"at": NOW.isoformat(), "session": "s1"}})
        self.assertIn("older", handoff.fresh(self.main, NOW + dt.timedelta(minutes=2)))
        self.write(NOW + dt.timedelta(minutes=1))
        self.assertIsNone(handoff.fresh(self.main, NOW + dt.timedelta(minutes=2)))

    def test_clear_starts_the_clear_and_continue_without_the_plan_guard(self):
        self.write(dt.datetime.now())
        code, out = self.run_cli("--clear")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls, [("clear-and-continue", "--pane", "%9", "--prompt", "/farmer act",
                                       "--without-plan", "--detach", "--json", "--session", "s1")])
        self.assertEqual(self.log()[-1]["kind"], "handoff-clear")
        self.answer = (1, '{"status": "refused", "reason": "already-running"}')
        self.assertEqual(self.run_cli("--clear")[0], 0)
        self.answer = (1, '{"status": "refused", "reason": "not-claude"}')
        code, out = self.run_cli("--clear")
        self.assertEqual(code, 1)
        self.assertIn("not-claude", out)
