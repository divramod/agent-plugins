"""Hal2 plan 0313 step 14 (D19): a red train's end never leaves its head on the carrier's remote branch for the next
train. The case of 2026-10-14 (the tollman's train.jsonl, UTC): train 09@11:02:43 went red at 11:18:02 and was
cleared at 11:27:09 (split after red), and the next train 09@11:47:24 formed on the same base; its landing's push to
origin/tollman-hal2 was refused at 11:52:57 as not a fast-forward, because the remote still held the red
train's merge (the farmer's 17-4: three times that day). The new train's form puts the remote back on its base
(`carrier.push_base`, leased) whatever the earlier end did; a retry keeps the red head there, since it lands it
again. On engine_farm's farm (a bare origin, no landing, D5)."""

import os
import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import train_state
from engine_farm import OWN, Farm, out
from test_farmer import git

REF = f"refs/heads/{OWN}"


class RedCarrier(Farm):
    def setUp(self):
        super().setUp()
        self.origin = self.tmp / "hal2.git"
        self.crop("09", {"nine.txt": "9"}, plan="0274-masterplan-halverse-plugin")

    def landing_push(self):
        """What the landing does with the carrier first: its head pushed to its remote branch, without force."""
        return engine.git(str(self.wm), "push", "-q", "origin", f"HEAD:{REF}")

    def remote(self):
        code, sha = engine.git(str(self.origin), "rev-parse", "--verify", "-q", REF)
        return sha if code == 0 else None

    def last_line(self, kind):
        return [e for e in train_state.lines(str(self.main)) if e["kind"] == kind][-1]

    def red_train(self):
        """09's train formed, its landing pushed the carrier and went red: the red head."""
        self.round()
        self.assertEqual(self.landing_push()[0], 0, "the red train's landing pushed the carrier")
        self.ends({"status": "gate_failed", "run": "https://github.com/divramod/hal2/actions/runs/38553908506",
                   "red": [{"name": "02-hz01-host-x/claude-code-plugins-test"}]})
        self.gate.of(OWN).update(state="held", train=None, hold={"reason": "failed"})
        self.round()
        self.assertEqual(self.train()["state"], "red")
        return out(self.wm, "rev-parse", "HEAD")

    def refuse(self, on: bool):
        hook = self.origin / "hooks" / "pre-receive"
        if on:
            hook.write_text("#!/bin/sh\necho 'refused by the test' >&2\nexit 1\n")
            os.chmod(hook, 0o755)
        else:
            hook.unlink()

    def test_the_next_train_after_a_red_one_forms_with_the_remote_on_its_base_and_its_push_fast_forwards(self):
        base = out(self.wm, "rev-parse", "HEAD")
        dead = self.red_train()  # 11:18:02
        self.refuse(True)  # the red train's end did not put the remote back (here: its breakup's push refused)
        # 11:27:09: split after red; the unhitch call itself breaks the train up (chain.py, plan 0333 step 6)
        code = self.call("unhitch", "09", "--why", "test_roles.py reads PROTECT", "--by-user", repo=self.main)[0]
        self.assertEqual(code, 0, "the user's own unhitch (plan 0360 D3)")
        self.assertIsNone(self.train(), "the unhitch's chain broke the red train up")
        self.assertIn("still holds the dead train", self.last_line("cleared")["pushed"])
        self.assertEqual(self.remote(), dead)
        self.refuse(False)
        self.commit(self.fields["09"], "nine.txt", "9, fixed")
        self.gate.hitch("09", self.fields["09"])
        self.round()  # 11:47:24: the train of 09 forms again on the same base
        self.assertIn(("form", "run", "-"), self.last)
        self.assertEqual((self.train()["base"], self.remote()), (base, base), "the dead train is gone from origin")
        self.assertEqual(self.last_line("formed")["pushed"], f"origin's {REF} back on {base[:12]} (was {dead[:12]})")
        code, text = self.landing_push()  # 11:52:57 was refused here
        self.assertEqual(code, 0, f"the next train's push fast-forwards: {text}")

    def test_a_remote_on_a_train_that_landed_before_pushes_nothing(self):
        self.round()
        self.assertEqual(self.landing_push()[0], 0)
        landed = out(self.wm, "rev-parse", "HEAD")
        self.ends({"status": "landed", "run": "https://github.com/x/runs/1"}, land=True)
        self.round()
        self.assertIsNone(self.train(), "in the barn")
        git(self.main, "pull", "-q", "--ff-only")
        self.commit(self.main, "later.txt", "the barn moved on", push=True)
        self.crop("07", {"seven.txt": "7"})
        self.round()
        self.assertIn(("form", "run", "-"), self.last)
        self.assertNotIn("pushed", self.last_line("formed"), "the landed train is in the base's history")
        self.assertEqual(self.remote(), landed, "untouched: the next push fast-forwards it")
        self.assertEqual(self.landing_push()[0], 0)

    def test_a_retry_keeps_the_red_head_on_the_remote_and_its_push_fast_forwards(self):
        dead = self.red_train()
        self.assertEqual(self.call("retry", "--why", "rust-test timing under load")[0], 0)
        self.round()  # restart: the empty retry commit on the red head (step 13)
        self.assertEqual(self.remote(), dead, "a retry lands the red head again: nothing reset")
        self.assertEqual(out(self.wm, "rev-parse", "HEAD^"), dead)
        code, text = self.landing_push()
        self.assertEqual(code, 0, f"the retry's push fast-forwards, none of its commits dropped: {text}")
        self.assertEqual(self.remote(), out(self.wm, "rev-parse", "HEAD"))


if __name__ == "__main__":
    unittest.main()
