"""Hal2 plan 0611 step 7 (design.md §5, D9): the handoff against the role's open records. Generic: a scratch role with
two record kinds and its own contradiction rule; a role without records passes untouched (the farmer)."""

import dataclasses
import datetime as dt
import json
from unittest import mock

import handoff
import role_records
import roles
import wake
from test_farmer import Repo

WIRING = dataclasses.replace(roles.FARMER, role="scratch")


def against_hold(record: dict, sentence: str) -> bool:
    return "trains form" in sentence and "no trains form" not in sentence


class Records(Repo):
    def setUp(self):
        super().setUp()
        saved = dict(role_records.KINDS), dict(role_records.CONTRA)
        self.addCleanup(lambda: (role_records.KINDS.clear(), role_records.KINDS.update(saved[0]),
                                 role_records.CONTRA.clear(), role_records.CONTRA.update(saved[1])))
        role_records.register("scratch", {"fix-order": role_records.Kind("fix_order"),
                                          "standing": role_records.Kind("user")})
        role_records.register_contra("scratch", {"standing": against_hold})
        self.main = str(self.main)
        self.calls = []
        p = mock.patch.object(wake.deliver, "cli", lambda *a, timeout=30: (self.calls.append(a), (0, "{}"))[1] if a[0] != "list"
                              else (0, json.dumps([{"pane_id": "%9", "checkout": str(self.slot), "session_id": "s"}])))
        p.start()
        self.addCleanup(p.stop)
        self.r1 = role_records.add(self.main, "scratch", "fix-order", "07", "fix 07", "tollman")["id"]
        self.r2 = role_records.add(self.main, "scratch", "standing", "-", "hold: CI rebuild", "user", rule="hold")["id"]

    def write(self, text: str):
        f = handoff.path(self.main, WIRING)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)

    def problems(self, text: str) -> list[str]:
        self.write(text)
        return handoff.records_problems(self.main, WIRING)

    def test_an_unmentioned_open_record_is_refused_and_all_named_passes(self):
        bad = self.problems(f"# handoff\n\n- {self.r1} fix-order 07: waits for CI\n")
        self.assertEqual(len(bad), 1)
        self.assertIn(f"{self.r2} (standing -) is open and not named", bad[0])
        self.assertEqual(self.problems(f"- {self.r1} waits for CI\n- {self.r2} hold stays, no trains form\n"), [])
        self.assertEqual(self.problems(f"{self.r1}, {self.r2}"), [])

    def test_an_id_is_a_whole_word(self):
        role_records.add(self.main, "scratch", "fix-order", "09", "fix 09", "tollman")
        names = self.problems(f"{self.r1} and {self.r2} and R30")
        self.assertEqual(len(names), 1)
        self.assertIn("R3 (fix-order 09)", names[0])

    def test_a_record_said_to_be_done_while_open_is_a_contradiction(self):
        bad = self.problems(f"- {self.r1} is fixed and landed.\n- {self.r2} stays\n")
        self.assertEqual(len(bad), 1)
        self.assertIn(f"{self.r1} is open, but the handoff says it is done", bad[0])
        self.assertEqual(self.problems(f"- {self.r1} is not fixed yet; {self.r2} stays\n"), [])
        self.assertEqual(self.problems(f"- {self.r1} still open, nothing landed\n- {self.r2} stays\n"), [])
        self.assertEqual(len(self.problems(f"- {self.r1} open, {self.r2} dropped\n")), 1, "only the id it follows")

    def test_a_sentence_against_an_open_order_is_a_contradiction(self):
        bad = self.problems(f"- {self.r1} waits. {self.r2} is open, but trains form again.\n")
        self.assertEqual(len(bad), 1)
        self.assertIn(f"goes against {self.r2}", bad[0])
        self.assertEqual(self.problems(f"- {self.r1} waits. {self.r2}: no trains form.\n"), [])

    def test_a_role_without_records_and_a_missing_handoff_pass(self):
        self.assertEqual(handoff.records_problems(self.main), [], "the farmer has no record kinds")
        self.assertEqual(handoff.records_problems(self.main, WIRING), [], "no handoff.md yet")
        done = role_records.close(self.main, "scratch", self.r1, "fix_order", "x")
        self.assertTrue(done)
        self.assertEqual(self.problems(f"{self.r2} only"), [], "a closed record needs no mention")

    def test_clear_refuses_a_failing_handoff_before_anything_else_and_starts_a_good_one(self):
        self.write(f"{self.r1} fixed.\n")
        code, what = handoff.clear(str(self.slot), self.main, dt.datetime.now(), WIRING)
        self.assertEqual((code, self.calls), (1, []))
        self.assertIn(f"{self.r2} (standing -) is open and not named", what)
        self.assertIn(f"{self.r1} is open, but the handoff says it is done", what)
        self.write(f"{self.r1} waits for CI. {self.r2} holds.\n")
        code, what = handoff.clear(str(self.slot), self.main, dt.datetime.now(), WIRING)
        self.assertEqual(code, 0, what)
        self.assertEqual(self.calls[0][0], "clear-and-continue")
