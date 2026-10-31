"""Hal2 plan 0490 step 10: a fix order's answer when the landing is over but the train still reads `landing`, the
redundant order, the fix left local, and the hold re-read before a start. On engine_farm.py's farm, gh is
gh_fake.py's (Train20 of test_early_order: train 20+02 lands, 20's early order stands).

- L47 (2026-10-20 07:34Z): train 3's `done fixed` came after its run completed; `fixed` refused "still runs" until
  the round wrote the red line minutes later
- L108 (2026-10-29 13:24Z): under the hold the landing was stopped by signal, no red line ever came: 09-fix-2's
  answer was refused for good
- L107 (2026-10-29 12:32Z): under the hold, settle restarted the stopped landing twice
- L88 (2026-10-24 02:24Z): train 14 started its landing a minute after the hold was set
- L56 (2026-10-20 13:38Z): two orders for one red; the second fix was redundant and had no way to close
- L106 (2026-10-29 11:36Z): 23-6's fix sat on the local 23-train-fix (its pre-push refused the train's CHANGELOG),
  the session ended, the train waited red 2 h
"""

import datetime as dt
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import acks
import engine
import hold
import leavers
import orders
import train_state
from engine_farm import out
from test_early_order import Train20
from test_farmer import git
from test_orders import Orders


class Ended(Train20):
    def ordered(self):
        """The round places 20's early order; 20's foreman pushes its fix and acks it."""
        self.round()
        sha = self.fix()
        ((_, msg),) = self.typed
        ack = msg.split("]")[0].removeprefix("tollman [")
        self.assertEqual(acks.main(["ack", ack, "done", "fixed", sha, "--repo", str(self.wm), "--role", "tollman"]), 0)
        return sha

    def held(self):
        hold.path(str(self.main)).write_text(json.dumps({"why": "the user's hold", "at": "2026-10-29T12:00:00Z"}))

    def merged(self, sha):
        self.assertEqual((self.train()["state"], out(self.cw, "rev-parse", "HEAD^2")), ("retry", sha))
        red = [e for e in train_state.lines(str(self.main)) if e["kind"] == "red"]
        self.assertEqual(len(red), 1, "one red line, written by `fixed`")
        self.assertIn("L108", red[0]["why"])

    def test_l108_a_landing_stopped_by_signal_counts_as_ended_and_the_fix_merges(self):
        sha = self.ordered()
        self.alive.clear()  # the user's hold: the landing stopped by signal, no result, no red line
        code, text = self.call("fixed", "20", sha)
        self.assertEqual(code, 0, text)
        self.merged(sha)
        self.assertEqual(engine.red(str(self.cw), "interrupted")[0], 0)
        self.assertEqual(len([e for e in train_state.lines(str(self.main)) if e["kind"] == "red"]), 1,
                         "the round's later red finds no landing: never a second line")

    def test_l47_the_run_told_finished_waits_for_the_landing_s_process_then_merges(self):
        sha = self.ordered()
        t = self.train()
        leavers.write(str(self.main), "watch-events.json", {"run": "720", "train": t["train"],
                                                            "started": t["started"], "seen": ["done:720"]})
        waited = []
        # orders' own clock only: patching time.sleep itself also caught subprocess's wait backoff on Linux
        clock = mock.Mock(wraps=orders.time, sleep=lambda s: waited.append(s) or self.alive.clear())
        with mock.patch.object(orders, "time", clock):
            code, text = self.call("fixed", "20", sha)
        self.assertEqual((code, waited), (0, [1]), text)
        self.merged(sha)

    def test_a_landing_whose_process_lives_and_whose_run_is_not_told_finished_still_waits(self):
        sha = self.ordered()
        with mock.patch.object(orders.time, "sleep", side_effect=AssertionError("no wait without the watch's word")):
            code, text = self.call("fixed", "20", sha)
        self.assertEqual(code, 1)
        self.assertIn("still runs", text)

    def test_a_landing_that_landed_is_never_taken_for_red(self):
        sha = self.ordered()
        self.ends({"status": "landed", "run": self.url, "commit": "c" * 40})
        code, text = self.call("fixed", "20", sha)
        self.assertEqual(code, 1)
        self.assertIn("the train landed", text)
        self.assertNotIn("red", [k for k, _ in self.state()])

    def test_l107_l108_under_the_hold_nothing_restarts_and_the_answer_is_taken_by_code(self):
        sha = self.ordered()
        self.held()
        self.ends(None)  # stopped by signal: no result
        self.round()
        self.assertNotIn(("restart", "run", "-"), self.last, "L107: the hold before settle's restart")
        self.assertIn(("held", "record", "-"), self.last)
        self.assertIn(("fixed", "run", "20"), self.last, "L108: the answered order taken while held")
        self.merged(sha)
        self.round()
        self.assertEqual(self.last, [("held", "record", "-")], "retry waits for unhold")

    def test_l88_the_hold_is_read_again_right_before_the_start_and_the_push(self):
        self.ends(None)
        self.held()
        starts = self.train()["starts"]
        code, text = engine.restart(str(self.cw))
        self.assertEqual(code, 0, text)
        self.assertIn("not started: held: the user's hold", text)
        self.assertEqual(self.train()["starts"], starts, "no started line")
        printed = io.StringIO()
        with redirect_stdout(printed):
            self.assertEqual(hold.stops(str(self.cw)), 1)
        self.assertEqual(json.loads(printed.getvalue())["status"], "held")
        hold.path(str(self.main)).unlink()
        self.assertEqual(hold.stops(str(self.cw)), 0)

    def test_l106_a_fix_left_local_over_30_min_wakes_once(self):
        self.round()
        path = self.fields["20"]
        git(path, "fetch", "-q", "origin", self.c)
        git(path, "switch", "-q", "-C", "20-train-fix", f"origin/{self.c}")
        (path / "code/x/twenty.py").write_text("20, fixed")
        git(path, "commit", "-qam", "fix 20")  # never pushed: the pre-push refused it
        self.ends({"status": "gate_failed", "run": self.url, "red": [{"name": "d1-01-rust-test"}]})
        self.round()
        self.assertEqual(self.train()["state"], "fixing")
        rows, at = train_state.lines(str(self.main)), self.train()["orders"][0]["at"]
        now = dt.datetime.fromisoformat(at.replace("Z", "+00:00"))
        self.assertEqual(orders.answers(str(self.cw), rows, [], now + dt.timedelta(minutes=29)), [])
        (wake,) = orders.answers(str(self.cw), rows, [], now + dt.timedelta(minutes=31))
        local = out(path, "rev-parse", "HEAD")
        self.assertEqual((wake["kind"], wake["key"]), ("fix-unpushed", f"unpushed:20-fix-1:{local}"))
        self.assertIn("HAL2_PRE_PUSH=0 git push origin", wake["text"])
        git(path, "push", "-q", "origin", "20-train-fix")
        self.assertEqual(orders.answers(str(self.cw), rows, [], now + dt.timedelta(minutes=31)), [], "pushed: none")


class Redundant(Orders):
    def test_l56_a_redundant_order_closes_on_the_carrier_s_head_and_the_train_lands_again(self):
        self.assertEqual(self.call("order", "07", "--why", "records red")[0], 0)
        self.assertEqual(self.call("order", "09", "--why", "the same records red")[0], 0)
        self.assertEqual(self.call("fixed", "07", self.fix("07"))[0], 0)
        head = out(self.cw, "rev-parse", "HEAD")
        self.assertEqual(self.call("fixed", "09")[0], 2, "neither a sha nor --redundant")
        code, text = self.call("fixed", "09", "--redundant")
        self.assertEqual(code, 0, text)
        line = train_state.lines(str(self.main))[-1]
        self.assertEqual((line["kind"], line["id"], line["sha"], line["redundant"]), ("fixed", "09-fix-1", head, True))
        self.assertEqual((self.train()["state"], out(self.cw, "rev-parse", "HEAD")), ("retry", head), "nothing merged")

    def test_the_order_text_names_the_push_without_pre_push_and_the_whole_red_job(self):
        self.assertEqual(self.call("order", "07", "--why", "its test fails")[0], 0)
        ((_, msg),) = self.typed
        for part in ("HAL2_PRE_PUSH=0 git push origin 07-train-fix", "run the whole red job",
                     "code/bash/scripts/gate/test-select.bats"):
            self.assertIn(part, msg)


def load_tests(loader, tests, pattern):
    """Only this file's own tests: Train20's and Orders' run in their own files."""
    return unittest.TestSuite(cls(name) for cls in (Ended, Redundant) for name in loader.getTestCaseNames(cls)
                              if name in vars(cls))

if __name__ == "__main__":
    unittest.main()
