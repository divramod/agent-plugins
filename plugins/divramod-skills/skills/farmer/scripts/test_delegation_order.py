"""Hal2 plan 0695 row 25 (D26, D42 1): waiting delegations start in a set order; a paused field gets no send."""

import contextlib
import io
import unittest
from unittest import mock

import delegation
import delegation_order
import delegation_round
import farmer
from test_delegation import MAIN, NOW, Ledger, flaky


def waiting_entry(key, **extra):
    with mock.patch.object(delegation, "start", lambda *a, **k: {"wait": delegation.NO_FIELD}):
        r = delegation.delegate(dict(flaky(), key=key, text=key, **extra), MAIN, 0, False, NOW)
    assert r["state"] == "waiting", r
    return r


class Order(unittest.TestCase):
    def test_oldest_first_user_first_and_before_puts_an_entry_ahead_of_its_key(self):
        w = lambda k, **e: {"key": k, **e}
        self.assertEqual([x["key"] for x in delegation_order.order([w("a"), w("b"), w("c")])], ["a", "b", "c"])
        got = delegation_order.order([w("a"), w("b"), w("c", before="a"), w("u", user=True)])
        self.assertEqual([x["key"] for x in got], ["u", "c", "a", "b"])
        got = delegation_order.order([w("a"), w("b", before="gone"), w("c", before="c")])
        self.assertEqual([x["key"] for x in got], ["a", "b", "c"], "a key that waits nowhere is ignored")


class Started(Ledger):
    def test_before_decides_the_start_order_and_survives_in_the_ledger(self):
        for k in ("brief:a", "brief:b"):
            waiting_entry(k)
        waiting_entry("brief:c", before="brief:a")
        self.assertEqual(delegation.ledger(MAIN)["brief:c"]["before"], "brief:a")
        started = delegation_round.place(MAIN, {}, 2, False, NOW, None)
        self.assertEqual([(d["key"], d["state"]) for d in started], [("brief:c", "running"), ("brief:a", "running")])
        self.assertEqual(delegation.ledger(MAIN)["brief:b"]["state"], "waiting")

    def test_without_before_the_oldest_starts_first(self):
        for k in ("brief:a", "brief:b", "brief:c"):
            waiting_entry(k)
        started = delegation_round.place(MAIN, {}, 2, False, NOW, None)
        self.assertEqual([d["key"] for d in started], ["brief:a", "brief:b"])

    def test_the_cli_flag_is_passed_to_the_delegation(self):
        args = farmer.parser().parse_args(["delegate", "--brief", "b.md", "--title", "t", "--before", "brief:a"])
        self.assertEqual(args.before, "brief:a")


class NoJumping(Ledger):
    def test_a_new_delegation_with_room_joins_the_waiters_instead_of_jumping_them(self):
        waiting_entry("brief:a")
        r = delegation.delegate(dict(flaky(), key="brief:n", text="n"), MAIN, 5, False, NOW)
        self.assertEqual(r["state"], "waiting")
        started = delegation_round.place(MAIN, {}, 5, False, NOW, None)
        self.assertEqual([d["key"] for d in started], ["brief:a", "brief:n"])

    def test_the_users_order_still_starts_at_once(self):
        waiting_entry("brief:a")
        r = delegation.delegate(dict(flaky(), key="brief:u", text="u", user=True), MAIN, 5, False, NOW)
        self.assertEqual(r["state"], "running")

    def test_an_unknown_before_key_is_refused_naming_the_waiting_keys(self):
        waiting_entry("brief:a")
        args = farmer.parser().parse_args(["delegate", "--brief", "b.md", "--title", "t", "--before", "brief:zz", "--repo", MAIN])
        err = io.StringIO()
        with mock.patch.object(farmer.tick.mtm_scan, "main_checkout", lambda r: MAIN), contextlib.redirect_stderr(err):
            self.assertEqual(farmer.run_delegate(args), 2)
        self.assertIn("brief:zz", err.getvalue())
        self.assertIn("brief:a", err.getvalue())
        self.assertEqual(list(delegation.ledger(MAIN)), ["brief:a"])


class PausedField(Ledger):
    def test_a_paused_free_field_gets_no_send_the_next_free_one_does(self):
        self.free = [{"slot": "05", "worktree": "05", "pane": "%5"}, {"slot": "06", "worktree": "06", "pane": "%6"}]
        self.paused = {"05": {"by": "user", "why": "stopped", "since": ""}}
        sent = []
        with mock.patch.object(delegation.deliver, "send", lambda pane, text: sent.append(pane) or 0):
            r = delegation.start("prompt", MAIN, False)
        self.assertEqual((sent, r["slot"]), (["%6"], "06"))

    def test_only_paused_free_fields_means_a_new_field_not_a_send(self):
        self.free = [{"slot": "05", "worktree": "05", "pane": "%5"}]
        self.paused = {"05": {"by": "user", "why": "stopped", "since": ""}}
        with mock.patch.object(delegation.deliver, "send", side_effect=AssertionError("sent to a paused field")):
            r = delegation.start("prompt", MAIN, False)
        self.assertEqual(r["how"], "new")


if __name__ == "__main__":
    unittest.main()
