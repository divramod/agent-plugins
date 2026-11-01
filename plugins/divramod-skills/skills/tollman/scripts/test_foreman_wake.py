"""Hal2 plan 0522 step 10 (D21): an order to a car's foreman starts its sleeping field first; a paused field is never
started, the farmer is told. Fakes only: no agents list, no session started, no `hal2-cli-git` called."""
# enforces .adr/paused-fields-never-woken.md and .adr/tollman.md (amendment 2026-10-31, D21)

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import board
import field_pause
import foreman_wake as fw
import mtm_scan
import orders_cli
import tick
import train_state
from tick import act

NOW = dt.datetime(2026, 10, 31, 12, 0)
MAIN = "/x/hal2"
TRAIN = "27+30@2026-10-31T11:00:00Z"
FIX = ("tollman (wagon train): fix order 27-fix-1 for field 27: train " + TRAIN + " is red (ts-test). Run: r. "
       "Why: w.\nIn your field: ...")
RESOLVE = "tollman (wagon train): resolve order 27-resolve-1 for field 27: train " + TRAIN + " carries your crop ..."
ROWS = [{"kind": "formed", "train": TRAIN, "slot": "tollman-train-1", "cars": [{"field": "27"}, {"field": "30"}]},
        {"kind": "started", "train": TRAIN}, {"kind": "red", "train": TRAIN, "why": "ts-test"},
        {"kind": "order", "train": TRAIN, "field": "27", "id": "27-fix-1", "branch": "27-train-fix", "base": "b" * 12}]


def order(kind="fix-order", text=FIX, pane=None):
    key = f"order:{TRAIN}:27:1" if kind == "fix-order" else f"resolve:{TRAIN}:27-resolve-1"
    return act("trains", kind, "send", "27", pane=pane, key=key, text=text)


def agent(state="idle", pane="t:27"):
    return {"kind": "claude", "pane_id": pane, "state": state, "slot": "27",
            "checkout": str(fw.field_path(MAIN, "27"))}


def ctx(agents=(), log=(), paused=None, now=NOW):
    rows = None if agents is None else list(agents)
    return {"main": MAIN, "now": now, "log": list(log), "agents": rows, "paused_fields": paused or {},
            "panes": {a["slot"]: a["pane_id"] for a in rows or []}}


def logged(a: dict, at=NOW, note="") -> dict:
    """The frame's log line of an executed act (tick.execute), at `at`."""
    return {"at": at.isoformat(), "kind": a["kind"], "slot": a["slot"], "what": a.get("text", ""), "note": note,
            "do": a["do"], "key": a.get("key", ""), "duty": a["duty"], "by": "tick"}


def runs(acts):
    return [a for a in acts if a["do"] == "run"]


class Gate(unittest.TestCase):
    def test_a_running_field_is_ordered_directly(self):
        a = order(pane="t:27")
        self.assertEqual(fw.gate([a], ctx([agent()])), [a])

    def test_an_unreadable_agents_list_never_starts(self):
        a = order()
        self.assertEqual(fw.gate([a], ctx(None)), [a])

    def test_other_acts_pass_untouched(self):
        others = [act("trains", "landed", "send", "27", key="x", text="in the barn"),
                  act("trains", "fix-order-main", "wake", key="y", text="main")]
        self.assertEqual(fw.gate(others, ctx()), others)

    def test_a_sleeping_field_is_started_then_ordered(self):
        a = order()
        first = fw.gate([a], ctx())
        start = runs(first)
        self.assertEqual(len(start), 1)
        argv = start[0]["argv"]
        self.assertEqual(argv[argv.index("--") + 1:],
                         ["hal2-cli-git", "worktree", "run", "27", "--agent", "claude", "--detach"])
        self.assertNotIn("--prompt", argv)  # the field's own conversation is resumed
        self.assertTrue(field_pause.starts_session(start[0]))  # the frame's pause guard still sees it as a start
        self.assertEqual(start[0]["key"], f"{fw.START}:{a['key']}")
        self.assertNotIn("send", [x["do"] for x in first])  # the order waits for the session
        held = [x for x in first if x["kind"] == fw.HELD]
        self.assertEqual(held[0]["text"], FIX)
        # the next round: the session rests; the held order is planned again and goes to its pane
        log = [logged(x, NOW) for x in first]
        later = ctx([agent("idle")], log, now=NOW + dt.timedelta(minutes=2))
        again = fw.held(later, ROWS)
        self.assertEqual([(x["do"], x["key"], x["pane"]) for x in again], [("send", a["key"], "t:27")])
        self.assertEqual(fw.gate(again, later), again)

    def test_no_second_start(self):
        a = order()
        start = runs(fw.gate([a], ctx()))[0]
        log = [logged(start, NOW)]
        soon = fw.gate([a], ctx([], log, now=NOW + dt.timedelta(minutes=3)))
        self.assertEqual(runs(soon), [])
        self.assertEqual([x["kind"] for x in soon], [fw.HELD])
        late = fw.gate([a], ctx([], log, now=NOW + fw.START_WAIT))
        self.assertEqual(late, [a])  # no session after the wait: the order goes as before (a relay), no start
        failed = fw.gate([a], ctx([], [logged(start, NOW, note=" (exit 1)")], now=NOW + dt.timedelta(minutes=1)))
        self.assertEqual(failed, [a])

    def test_two_orders_of_one_round_start_the_field_once(self):
        b = act("trains", "fix-order", "send", "27", key=f"order:{TRAIN}:27:also:ts-test", text=FIX + " also")
        self.assertEqual(len(runs(fw.gate([order(), b], ctx()))), 1)

    def test_a_held_order_is_sent_once(self):
        first = fw.gate([order()], ctx())
        log = [logged(x) for x in first] + [logged({**order(), "do": "send"}, NOW + dt.timedelta(minutes=1))]
        self.assertEqual(fw.held(ctx([agent()], log), ROWS), [])
        closed = ROWS + [{"kind": "fixed", "train": TRAIN, "field": "27", "id": "27-fix-1"}]
        self.assertEqual(fw.held(ctx([agent()], [logged(x) for x in first]), closed), [])


class Paused(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(mtm_scan, "DATA", tmp)
        p.start()
        self.addCleanup(p.stop)
        self.pause = {"27": {"by": "farmer", "why": "reading its handoff", "since": "2026-10-31T09:00:00Z"}}

    def test_a_paused_field_is_never_started_and_the_farmer_is_told(self):
        out = fw.gate([order()], ctx([], paused=self.pause))
        self.assertEqual(runs(out), [])
        self.assertNotIn("send", [x["do"] for x in out])
        note = [x for x in out if x["kind"] == fw.NOTE][0]
        self.assertEqual((note["do"], note["slot"]), ("record", mtm_scan.roles.slot_name(MAIN)))
        self.assertIn("field 27 is paused", note["text"])
        self.assertIn("27-fix-1", note["text"])
        self.assertIn(fw.NOTE, board.NOTES)  # the frame's record becomes a note on the farmer's board
        self.assertEqual([x["kind"] for x in out if x["kind"] == fw.HELD], [fw.HELD])  # sent after the resume

    def test_a_paused_fields_conflict_is_resolved_in_the_train(self):
        out = fw.gate([order("resolve-order", RESOLVE)], ctx([], paused=self.pause))
        self.assertEqual(runs(out), [])
        wake = [x for x in out if x["do"] == "wake"]
        self.assertEqual(len(wake), 1)
        self.assertIn("resolve it in the train yourself", wake[0]["text"])
        self.assertIn("tollman.py resolved 27", wake[0]["text"])
        self.assertIn("resolves the conflict in the train itself", [x for x in out if x["kind"] == fw.NOTE][0]["text"])

    def test_the_start_writes_the_trains_woke_line(self):
        for row in ROWS:
            train_state.append(MAIN, row["kind"], row["slot"] if "slot" in row else "tollman-train-1",
                               **{k: v for k, v in row.items() if k not in ("kind", "slot")})
        seen = []
        argv = runs(fw.gate([order()], ctx()))[0]["argv"][3:]  # past python, the script and `start`
        self.assertEqual(fw.start(argv, guard=lambda a: seen.append(a) or 0), 0)
        self.assertEqual(seen[0][seen[0].index("--") + 1:][:4], ["hal2-cli-git", "worktree", "run", "27"])
        woke = [e for e in train_state.lines(MAIN) if e["kind"] == "woke"]
        self.assertEqual([(e["field"], e["id"], e["train"]) for e in woke], [("27", "27-fix-1", TRAIN)])
        self.assertEqual(train_state.standing(train_state.lines(MAIN))["state"], "fixing")  # woke changes no state
        self.assertEqual(fw.start(argv, guard=lambda a: 75), 75)  # a skipped start (a session is there): no line
        self.assertEqual(len([e for e in train_state.lines(MAIN) if e["kind"] == "woke"]), 1)


class Deliver(unittest.TestCase):
    def test_tollman_order_starts_the_sleeping_field_instead_of_sending(self):
        done = []
        with mock.patch.object(tick, "execute", side_effect=lambda a, *rest: done.append(a)):
            orders_cli.deliver("/x/tollman", MAIN, [order()], ctx(), SimpleNamespace(role="tollman"))
        self.assertEqual([a["do"] for a in done], ["run", "record"])
        self.assertIn("worktree", done[0]["argv"])


if __name__ == "__main__":
    unittest.main()
