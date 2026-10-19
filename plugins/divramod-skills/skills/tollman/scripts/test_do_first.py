"""Hal2 plan 0383 step 8 (rule 7, D8): `tollman.py act` after a clear prints the handoff's `## DO FIRST` first and closes
the wake items created before the handoff's last write. The replay is train 20: its train-red and fix-refused were
shown again after the tollman's clear although the handoff's writer had seen them."""
# enforces .adr/deterministic-first.md

import datetime as dt
import os
from unittest import mock

import farmer_frame  # noqa: F401  (puts the farmer skill's scripts on the path)
import deliver
import handoff
import tick
import wake
from test_farmer import NOW
from test_tollman import WIRING, Field

HANDOFF = "# tollman handoff\n\n## DO FIRST\n\nRerun train 20 once; then check the runners.\n\n## Next\nlater\n"


class DoFirst(Field):
    def setUp(self):
        super().setUp()
        self.main = str(self.main)
        for p in (mock.patch.object(deliver, "send", return_value=None),
                  mock.patch.object(wake, "farmer_pane", return_value="%9")):
            p.start()
            self.addCleanup(p.stop)

    def hand_over(self, out, minutes):
        wake.hand_over(str(self.wm), self.main, out, NOW + dt.timedelta(minutes=minutes), WIRING)

    def write_handoff(self, minutes, text=HANDOFF):
        f = handoff.path(self.main, WIRING)
        f.write_text(text)
        stamp = (NOW + dt.timedelta(minutes=minutes)).timestamp()
        os.utime(f, (stamp, stamp))

    def test_train_20_after_a_clear_shows_do_first_then_only_the_newer_item(self):
        self.hand_over({"wake": [tick.act("trains", "train-red", "wake", "-", text="train 20 red", key="train-red:20")]}, 0)
        self.hand_over({"send": [], "wake": [tick.act("trains", "fix-refused", "wake", "09", text="fix refused for 09")]}, 1)
        self.write_handoff(10)
        self.hand_over({"wake": [tick.act("trains", "train-red", "wake", "-", text="train 21 red", key="train-red:21")]}, 20)
        code, out = self.call("act")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("DO FIRST (from "), out)
        self.assertIn("Rerun train 20 once; then check the runners.", out)
        self.assertLess(out.index("Rerun train 20"), out.index("train-red"))
        self.assertNotIn("train 20 red", out)
        self.assertNotIn("fix refused for 09", out)
        self.assertIn("closed 2 items older than the handoff: train-red -, fix-refused 09", out)
        self.assertIn("train 21 red", out)
        self.assertTrue(out.rstrip().endswith("2 items, woken 2026-10-03T10:20:00"), out)  # item 0: the handoff
        self.assertEqual([i["text"] for i in wake.read(self.main, WIRING)["items"]], ["train 21 red"])
        code, again = self.call("act")
        self.assertNotIn("closed", again, "closed once, not again")

    def test_without_a_do_first_text_the_path_is_named_and_json_closes_too(self):
        self.hand_over({"wake": [tick.act("trains", "train-red", "wake", "-", text="train 20 red")]}, 0)
        self.write_handoff(5, "# tollman handoff\n\n## Next\nx\n")
        code, out = self.call("act")
        self.assertIn("  0 read   handoff/handoff", out)  # the handoff's item 0 names the file (hal2 plan 0393)
        self.assertIn("1 items", out)
        self.hand_over({"wake": [tick.act("trains", "train-red", "wake", "-", text="train 22 red")]}, 3)
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
