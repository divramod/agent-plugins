"""Hal2 plan 0383 step 8 (rule 7, D8): `tollman.py act` after a clear prints the handoff's `## DO FIRST` first and closes
the wake items created before the handoff's last write. The replay is train 20: its train-red and fix-refused were
shown again after the tollman's clear although the handoff's writer had seen them."""
# enforces .adr/deterministic-first.md

import datetime as dt
import json
import os
import types
from unittest import mock

import farmer_frame  # noqa: F401  (puts the farmer skill's scripts on the path)
import deliver
import handoff
import red_orders
import roletime
import state_cmd
import train_cars
import tick
import train_state
import wake
from test_farmer import NOW
from test_tollman import WIRING, Field

HANDOFF = "# tollman handoff\n\n## DO FIRST\n\nRerun train 20 once; then check the runners.\n\n## Next\nlater\n"


class Frame(Field):
    def setUp(self):
        super().setUp()
        self.main = str(self.main)
        # act ends with red_orders.report (gh + train.jsonl, its own tests: test_red_orders); here only the keep-hook reads train.jsonl
        for p in (mock.patch.object(deliver, "send", return_value=None),
                  mock.patch.object(red_orders, "report", return_value=0),
                  mock.patch.object(wake, "farmer_pane", return_value="%9")):
            p.start()
            self.addCleanup(p.stop)

    def hand_over(self, out, minutes):
        wake.hand_over(str(self.wm), self.main, out, NOW + dt.timedelta(minutes=minutes), WIRING)

    def red_item(self, n, run=None, kind="train-red", text=None):
        """A wake item of train `n` red on `run` (a train-red, as early_order and train_red make it)."""
        ev = {"train": {"train": n}, "evidence": {"id": run}} if run else {"train": {"train": n}}
        return tick.act("trains", kind, "wake", "-", text=text or f"train {n} red", key=f"train-red:{run or n}", evidence=ev)

    def order(self, n, run):
        """An `order` line of train `n` in train.jsonl, its `run` a URL or a bare id as written."""
        train_state.append(self.main, "order", "09", NOW, train=n, field="09", id=f"o{n}", branch="09-train-fix",
                           base="origin/x", why="bash-test: red", run=run)

    def write_handoff(self, minutes, text=HANDOFF):
        f = handoff.path(self.main, WIRING)
        f.write_text(text)
        stamp = (NOW + dt.timedelta(minutes=minutes)).timestamp()
        os.utime(f, (stamp, stamp))


class DoFirst(Frame):
    def test_train_20_after_a_clear_shows_do_first_then_only_the_newer_item(self):
        self.order(20, "https://github.com/o/r/actions/runs/20000000001")
        self.hand_over({"wake": [self.red_item(20, "20000000001")]}, 0)
        self.hand_over({"send": [], "wake": [tick.act("trains", "fix-refused", "wake", "09", text="fix refused for 09")]}, 1)
        self.write_handoff(10)
        self.hand_over({"wake": [tick.act("trains", "train-red", "wake", "-", text="train 21 red", key="train-red:21")]}, 20)
        code, out = self.call("act")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("tollman state:"), out)  # plan 0611 step 6: the state is printed first
        self.assertLess(out.index("tollman state:"), out.index("DO FIRST (from "))
        self.assertIn("Rerun train 20 once; then check the runners.", out)
        self.assertLess(out.index("Rerun train 20"), out.index("train-red"))
        self.assertNotIn("train 20 red", out)
        self.assertNotIn("fix refused for 09", out)
        self.assertIn("closed 2 items older than the handoff: train-red -, fix-refused 09", out)
        self.assertIn("train 21 red", out)
        woken = roletime.stamp(NOW)  # the frame writes UTC `Z` (plan 0530), not a naive time
        self.assertTrue(out.rstrip().endswith(f"2 items, woken {woken}"), out)  # item 0: the handoff
        self.assertEqual([i["text"] for i in wake.read(self.main, WIRING)["items"]], ["train 21 red"])
        code, again = self.call("act")
        self.assertNotIn("closed", again, "closed once, not again")

    def test_without_a_do_first_text_the_path_is_named_and_json_closes_too(self):
        self.hand_over({"wake": [tick.act("trains", "relay", "wake", "-", text="train 20 note")]}, 0)
        self.write_handoff(5, "# tollman handoff\n\n## Next\nx\n")
        code, out = self.call("act")
        self.assertIn("  0 read   handoff/handoff", out)  # the handoff's item 0 names the file (hal2 plan 0393)
        self.assertIn("1 items", out)
        self.hand_over({"wake": [tick.act("trains", "relay", "wake", "-", text="train 22 red")]}, 3)
        code, out = self.call("act", "--json")
        self.assertNotIn("train 22 red", out)

    def test_handoff_rewrite_archives_the_old_handoff_and_the_new_one_is_a_fresh_write(self):
        """Plan 0383 step 9, D9: the tollman's rewrite moves handoff.md to handoff-archive/ beside it."""
        self.write_handoff(-5)
        f = handoff.path(self.main, WIRING)
        code, out = self.call("handoff", "--rewrite")
        self.assertEqual(code, 0, out)
        (old,) = (f.parent / "handoff-archive").iterdir()
        self.assertEqual(old.read_text(), HANDOFF)
        self.assertFalse(f.exists())
        self.assertIn("# tollman handoff", out)
        self.assertIn("## DO FIRST", out)
        self.assertNotIn("Rerun train 20", out)
        f.write_text("# tollman handoff\n\n## DO FIRST\n\nnew\n")
        self.assertGreater(handoff.written(self.main, WIRING), NOW.timestamp() + 3600)


class HandoffCutoff(Frame):
    """Plan 0608 D1, D2 (learning L240): `act` closes only the items the handoff's writer had seen, by the wake seq the
    clear recorded, never by handoff.md's mtime. The replay is train 51 run 2: the handoff was archived 15:30:30Z, the
    reds came 15:30:39Z, 15:33:14Z and 15:35:26Z, handoff.md was edited 15:35:28Z and act closed all three."""

    def red(self, n, minutes, ordered=False):
        """A train-red of train `n` on run 3000000000`n`; `ordered`: its order line is in train.jsonl."""
        if ordered:
            self.order(n, f"3000000000{n}")
        self.hand_over({"wake": [self.red_item(n, f"3000000000{n}")]}, minutes)

    def start_clear(self, minutes):
        with mock.patch.object(deliver, "agent", return_value={"session_id": "s1"}), \
                mock.patch.object(deliver, "cli", return_value=(0, json.dumps({"status": "started"}))):
            return handoff.clear(str(self.wm), self.main, NOW + dt.timedelta(minutes=minutes), WIRING)

    def texts(self):
        return [i["text"] for i in wake.read(self.main, WIRING)["items"]]

    def test_reds_after_the_clear_stay_open_though_the_handoff_is_edited_later(self):
        self.write_handoff(0)
        self.start_clear(1)
        self.red(51, 2)
        self.red(52, 4)
        self.red(53, 6)
        self.write_handoff(7)  # the edit after the last red: its mtime is newer than every item
        code, out = self.call("act")
        self.assertEqual(code, 0, out)
        self.assertNotIn("closed", out)
        self.assertEqual(self.texts(), ["train 51 red", "train 52 red", "train 53 red"])

    def test_an_item_the_writer_saw_is_closed_and_a_later_one_is_not(self):
        self.red(50, 0, ordered=True)
        self.write_handoff(1)
        self.assertEqual(self.start_clear(2)[0], 0)
        self.assertEqual(wake.read(self.main, WIRING)["handoff_seq"], 1)
        self.red(51, 3)
        self.write_handoff(9)
        code, out = self.call("act")
        self.assertIn("closed 1 items older than the handoff: train-red -", out)
        self.assertEqual(self.texts(), ["train 51 red"])
        self.assertEqual(wake.read(self.main, WIRING)["items"][0]["seq"], 2, "numbering goes on past the handoff's")

    def test_the_seq_keeps_counting_after_every_item_was_done(self):
        self.red(50, 0, ordered=True)
        self.write_handoff(1)
        self.start_clear(2)
        wake.done(self.main, 1, WIRING)  # the batch is dropped; wake.json still holds the handoff's seq
        self.red(51, 3)
        self.assertEqual(wake.read(self.main, WIRING)["items"][0]["seq"], 2)
        self.write_handoff(9)
        self.assertEqual(self.call("act")[0], 0)
        self.assertEqual(self.texts(), ["train 51 red"])

    def test_a_clear_with_no_item_yet_still_protects_the_next_ones(self):
        self.write_handoff(0)
        self.start_clear(1)
        self.red(51, 2)
        self.write_handoff(5)
        self.call("act")
        self.assertEqual(self.texts(), ["train 51 red"])

    def test_a_wake_json_without_handoff_seq_falls_back_to_the_mtime(self):
        self.red(50, 0, ordered=True)
        self.red(51, 20)
        self.write_handoff(10)
        data = wake.read(self.main, WIRING)
        self.assertNotIn("handoff_seq", data)
        code, out = self.call("act")
        self.assertIn("closed 1 items older than the handoff: train-red -", out)
        self.assertEqual(self.texts(), ["train 51 red"])


class UnorderedRedsStay(Frame):
    """Plan 0608 D3 (learning L240, rule L230): `act` never closes a `train-red` or `train-failed` item no `order` line of
    train.jsonl answers for its train and run; the seen item is closed once an order line is there (its `run` a URL or a
    bare id) and an item of any other kind closes as before. The replay is train 51 run 2: three reds, no order."""
    RUN = "29999999999"

    def texts(self):
        return [i["text"] for i in wake.read(self.main, WIRING)["items"]]

    def act(self, item):
        self.hand_over({"wake": [item]}, 0)
        self.write_handoff(5)
        return self.call("act")

    def test_a_seen_train_red_without_an_order_stays_open(self):
        code, out = self.act(self.red_item(51, self.RUN))
        self.assertEqual(code, 0, out)
        self.assertNotIn("closed", out)
        self.assertEqual(self.texts(), ["train 51 red"])

    def test_a_seen_train_failed_without_an_order_stays_open(self):
        self.order(50, self.RUN)  # another train's order answers nothing of train 51
        code, out = self.act(self.red_item(51, self.RUN, kind="train-failed", text="train 51 did not land"))
        self.assertNotIn("closed", out)
        self.assertEqual(self.texts(), ["train 51 did not land"])

    def test_an_order_of_another_run_of_the_train_answers_nothing(self):
        self.order(51, "https://github.com/o/r/actions/runs/20000000001")
        self.act(self.red_item(51, self.RUN))
        self.assertEqual(self.texts(), ["train 51 red"])

    def test_an_order_line_with_the_run_as_a_url_closes_it(self):
        self.order(51, f"https://github.com/o/r/actions/runs/{self.RUN}")
        code, out = self.act(self.red_item(51, self.RUN))
        self.assertIn("closed 1 items older than the handoff: train-red -", out)
        self.assertEqual(self.texts(), [])

    def test_an_order_line_with_a_bare_run_id_closes_it(self):
        self.order(51, self.RUN)
        code, out = self.act(self.red_item(51, self.RUN))
        self.assertIn("closed 1 items older than the handoff: train-red -", out)
        self.assertEqual(self.texts(), [])

    def test_an_item_naming_no_run_waits_for_any_order_of_its_train(self):
        item = tick.act("trains", "train-failed", "wake", "-", text="train 51 did not land", key="train-red:51:2",
                        evidence={"train": {"train": 51}, "result": None})
        self.act(item)
        self.assertEqual(self.texts(), ["train 51 did not land"])
        self.order(51, self.RUN)
        self.assertIn("closed 1", self.call("act")[1])

    def test_other_kinds_close_and_only_the_unordered_red_stays(self):
        self.hand_over({"wake": [self.red_item(51, self.RUN),
                                 tick.act("trains", "fix-refused", "wake", "09", text="fix refused for 09")]}, 0)
        self.write_handoff(5)
        code, out = self.call("act")
        self.assertIn("closed 1 items older than the handoff: fix-refused 09", out)
        self.assertEqual(self.texts(), ["train 51 red"])

    def test_train_jsonl_is_read_once_per_act_and_only_for_a_candidate(self):
        # the state printed before DO FIRST (plan 0611 step 6) reads train.jsonl through its own module name: not counted here
        own = types.SimpleNamespace(**vars(train_state))  # a copy, so the counting patch below misses it
        for mod in (state_cmd, train_cars):
            patch = mock.patch.object(mod, "train_state", own)
            patch.start()
            self.addCleanup(patch.stop)
        with mock.patch.object(train_state, "lines", wraps=train_state.lines) as lines:
            self.act(tick.act("trains", "fix-refused", "wake", "09", text="x"))
            self.assertEqual(lines.call_count, 0)
        with mock.patch.object(train_state, "lines", wraps=train_state.lines) as lines:
            self.hand_over({"wake": [self.red_item(51, self.RUN), self.red_item(52, "29999999998")]}, 1)
            self.write_handoff(9)
            self.call("act")
            self.assertEqual(lines.call_count, 1)
