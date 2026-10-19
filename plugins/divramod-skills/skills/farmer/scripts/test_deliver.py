"""The frame's typing into a session (deliver.py) and a refused send (tick.execute). These tests lived in
test_boss.py until the boss moved to the tollman skill (hal2 plan 0294 step 5); deliver.run is a fake."""

import json
import unittest
from unittest import mock

import deliver
import mtm_scan
import tick


class Prompt(unittest.TestCase):
    def test_send_asks_hal2_to_type_only_into_an_empty_box(self):
        self.assertEqual(
            deliver.if_empty("%8", "hi"), ["send", "%8", "hi", "--paste", "--if-empty", "--submit"])
        self.assertEqual(deliver.if_empty("%8", "hi", deliver.READY | {"failed"})[-2:], ["--allow-state", "failed"])
        err = 'hal2-cli-agents: not sent: draft: the input box holds "my draft"\n'
        self.assertEqual(deliver.refusal(err), 'draft: the input box holds "my draft"')

    def test_send_submits_in_one_call_and_reports_a_text_not_taken(self):
        err = "hal2-cli-agents: not submitted: not-taken: the session did not take the text after two Enters; " \
            "hal2's text was removed, the box is empty\n"
        with mock.patch.object(deliver, "run", return_value=(4, "", err)) as run:
            why = deliver.send("%8", "hi")
        self.assertEqual(run.call_count, 1, "no separate Enter")
        self.assertTrue(why.startswith("not-taken: "), why)
        with mock.patch.object(deliver, "run", return_value=(0, "", "")) as run:
            self.assertIsNone(deliver.send("%8", "hi"))
        self.assertEqual(run.call_count, 1)

    def test_the_refusals_of_an_older_and_a_newer_hal2_are_reported(self):
        # hal2 plan 0318 moved `not sent` 3 -> 10 and `not submitted` 4 -> 11.
        for code, err in ((3, "x: not sent: busy: working\n"), (10, "x: not sent: busy: working\n"),
                          (11, "x: not submitted: not-taken: gone\n")):
            with mock.patch.object(deliver, "run", return_value=(code, "", err)):
                self.assertFalse(deliver.send("%8", "hi").startswith("hal2-cli-agents"), code)

    def test_a_failure_s_body_is_read_from_stdout_or_the_error_document(self):
        # hal2 plan 0318 row 8: a refusal's old --json body is the error document's details on stderr.
        body = '{"status": "refused", "reason": "already-running", "message": "a job runs"}'
        doc = '{"error": {"code": "failed", "exit": 1, "message": "refused", "hint": null, "details": %s}}\n' % body
        for out, err in ((body, ""), ("", doc)):
            with mock.patch.object(deliver, "run", return_value=(1, out, err)):
                self.assertEqual(json.loads(deliver.cli("clear-and-continue", "--json")[1])["reason"], "already-running")
        empty = '{"error": {"code": "failed", "exit": 1, "message": "no host", "hint": null, "details": {}}}'
        for err in (empty, "hal2-cli-agents: no host\n"):
            with mock.patch.object(deliver, "run", return_value=(1, "", err)):
                self.assertEqual(deliver.cli("capture", "%8"), (1, ""))
        with mock.patch.object(deliver, "run", return_value=(0, "screen", doc)):
            self.assertEqual(deliver.cli("capture", "%8"), (0, "screen"))

    def test_an_agent_is_found_in_the_old_and_the_new_list(self):
        agent = {"pane_id": "%8", "state": "idle"}
        for out in ('[{"pane_id": "%8", "state": "idle"}]', '{"agents": [{"pane_id": "%8", "state": "idle"}]}'):
            with mock.patch.object(deliver, "cli", return_value=(0, out)):
                self.assertEqual(deliver.agent("%8"), agent, out)

    def test_send_falls_back_for_a_cli_without_submit(self):
        usage = "hal2-cli-agents: send takes <pane> <text> [--key | --paste] [--if-empty [--allow-state <state>]...]\n"
        calls = []

        def run(*args, timeout=30):
            calls.append(args)
            return (1, "", usage) if "--submit" in args else (0, "", "")

        with mock.patch.object(deliver, "run", side_effect=run):
            self.assertIsNone(deliver.send("%8", "hi"))
        self.assertEqual(calls[1], ("send", "%8", "hi", "--paste", "--if-empty"))
        self.assertEqual(calls[2], ("send", "%8", "enter", "--key"))

    def test_a_refused_send_becomes_a_relay(self):
        out = {"wake": [], "notify": []}
        a = tick.act("lead", "pause", "send", "08", pane="%8", text="pause", key="pause:L1:08")
        with mock.patch.object(deliver, "send", return_value="agent is working"), \
                mock.patch.object(mtm_scan, "log") as log:
            tick.execute(a, "/x/farmer", "/x/hal2", out)
        self.assertEqual([r["kind"] for r in out["relay"]], ["pause"])
        self.assertEqual(log.call_args.args[1]["do"], "relay")
        self.assertIn("agent is working", log.call_args.args[1]["note"])


if __name__ == "__main__":
    unittest.main()
