import datetime as dt
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import delegation
import due
import role_sync
import tick

NOW = dt.datetime(2026, 10, 6, 10, 0)
CTX = {"top": "/x/farmer", "main": "/x/hal2", "now": NOW, "log": []}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Plan(unittest.TestCase):
    def test_nothing_while_main_has_the_farmer_branchs_role(self):
        self.assertEqual(role_sync.plan_sync({}, CTX, {"differs": False, "sha": "abc"}, {}), [])

    def test_a_difference_is_one_direct_instruction_keyed_by_the_farmer_head(self):
        [a] = role_sync.plan_sync({}, CTX, {"differs": True, "sha": "abc"}, {})
        self.assertEqual((a["do"], a["duty"], a["key"]), ("delegate", "sync", "sync:abc"))
        self.assertIn("land now", a["prompt"])
        self.assertLess(a["prompt"].index("/mfm"), a["prompt"].index("git merge --no-edit {farmer_slot}"))
        self.assertLess(a["prompt"].index("git merge --no-edit {farmer_slot}"), a["prompt"].index("/mtm"))
        self.assertNotIn("/plan new", a["prompt"])

    def test_one_sync_at_a_time(self):
        for state in ("running", "waiting"):
            self.assertEqual(role_sync.plan_sync({}, CTX, {"differs": True, "sha": "def"},
                                                 {"sync:abc": {"state": state}}), [])
        self.assertEqual(len(role_sync.plan_sync({}, CTX, {"differs": True, "sha": "def"},
                                                 {"sync:abc": {"state": "landed"}})), 1)

    def test_sync_is_a_known_duty(self):
        self.assertIn("sync", due.DUTIES)


class State(unittest.TestCase):
    def test_role_state_compares_the_committed_role_with_origin_main(self):
        with tempfile.TemporaryDirectory() as d:
            origin, slot = Path(d) / "origin", Path(d) / "farmer"
            git(d, "init", "-q", "-b", "main", str(origin))
            git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "0")
            (origin / tick.ROLE).parent.mkdir(parents=True)
            (origin / tick.ROLE).write_text("a\n")
            git(origin, "add", tick.ROLE)
            git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "role")
            git(d, "clone", "-q", str(origin), str(slot))
            self.assertFalse(role_sync.role_state(str(slot))["differs"])
            (slot / tick.ROLE).write_text("b\n")
            self.assertFalse(role_sync.role_state(str(slot))["differs"])  # uncommitted: role_edit commits it first
            git(slot, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", "farmer-role")
            self.assertTrue(role_sync.role_state(str(slot))["differs"])


class Delegate(unittest.TestCase):
    def test_the_direct_instruction_replaces_the_plan_prompt_and_role_line_even_after_waiting(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(delegation.mtm_scan, "state_dir",
                                                                   return_value=Path(d)), \
                mock.patch.object(delegation.mtm_scan, "log"):
            [a] = role_sync.plan_sync({}, CTX, {"differs": True, "sha": "abc"}, {})
            with mock.patch.object(delegation, "has_room", return_value=False):
                self.assertEqual(delegation.delegate(a, "/x/hal2", "auto", False, NOW)["state"], "waiting")
            sent = []
            with mock.patch.object(delegation, "has_room", return_value=True), \
                    mock.patch.object(delegation, "start", side_effect=lambda p, m, dry, values=None: sent.append(p) or {"slot": "07"}):
                delegation.follow_up("/x/hal2", {}, "auto", False, NOW)
            self.assertIn("git merge --no-edit farmer", sent[0])
            role = next(Path(d, "servants").glob("*.md")).read_text()
            self.assertIn("No plan.", role)
            self.assertNotIn("/plan new", role)
            entries = [json.loads(line) for line in Path(d, "delegations.jsonl").read_text().splitlines()]
            self.assertEqual(entries[-1]["state"], "running")


if __name__ == "__main__":
    unittest.main()
