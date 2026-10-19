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

REAL_CLI = wake.deliver.cli


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
        # .adr/tollman-decides-trains.md: only a role with Wiring.session_effort (the tollman) passes --effort
        self.assertNotIn("--effort", self.calls[0], "the farmer's clear passes none (hal2 plan 0333)")
        self.assertEqual(self.log()[-1]["kind"], "handoff-clear")
        self.answer = (1, '{"status": "refused", "reason": "already-running"}')
        self.assertEqual(self.run_cli("--clear")[0], 0)
        self.answer = (1, '{"status": "refused", "reason": "not-claude"}')
        code, out = self.run_cli("--clear")
        self.assertEqual(code, 1)
        self.assertIn("not-claude", out)

    def test_a_newer_hal2_s_refusal_on_stderr_is_read(self):
        # hal2 plan 0318 row 8: clear-and-continue's refusal is the error document's details on stderr.
        self.write(dt.datetime.now())
        doc = {"error": {"code": "failed", "exit": 1, "message": "clear-and-continue refused: a job runs",
                         "hint": None, "details": {"status": "refused", "reason": "already-running"}}}

        def run(*args, timeout=30):
            if args[0] == "list":
                return 0, json.dumps({"agents": [{"pane_id": "%9", "checkout": str(self.slot), "session_id": "s1"}]}), ""
            return 1, "", json.dumps(doc) + "\n"

        with mock.patch.object(wake.deliver, "cli", REAL_CLI), mock.patch.object(wake.deliver, "run", run):
            self.assertEqual(self.run_cli("--clear")[0], 0)
            doc["error"]["details"]["reason"] = "not-claude"
            code, out = self.run_cli("--clear")
        self.assertEqual(code, 1)
        self.assertIn("not-claude", out)

    def test_the_template_starts_with_do_first_and_the_section_is_read_back(self):
        self.assertLess(handoff.TEMPLATE.index("## DO FIRST"), handoff.TEMPLATE.index("## The user's decisions"))
        self.assertEqual(handoff.do_first(self.main), "", "no handoff.md")
        f = handoff.path(self.main)
        f.write_text("# farmer handoff\n\n## DO FIRST\n\nAnswer 07.\nThen rerun train 20.\n\n## Next\nlater\n")
        self.assertEqual(handoff.do_first(self.main), "Answer 07.\nThen rerun train 20.")
        f.write_text("# farmer handoff\n\n## DO FIRST\n\n## Next\nlater\n")
        self.assertEqual(handoff.do_first(self.main), "", "an empty section prints nothing")
        f.write_text("# farmer handoff\n\n## Next\nlater\n")
        self.assertEqual(handoff.do_first(self.main), "")
        self.assertEqual(handoff.written(self.main), f.stat().st_mtime)
